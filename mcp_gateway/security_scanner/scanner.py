import json
import logging
import os # Added for path expansion and directory creation
from pathlib import Path # Added for path manipulation
from mcp_gateway.config import Constants, get_tool_params_description
from mcp_gateway.security_scanner.config import MarketPlaces, logger
from mcp_gateway.security_scanner.project_analyzer import ProjectAnalyzer
from mcp_gateway.security_scanner.tool_poisoning_analayzer import ToolAnalyzer
from mcp_gateway.server import GetewayContext
from typing import Tuple, Dict, List, Any

class Scanner:
    def __init__(self):
        self._mcp_reputation_analyzer = ProjectAnalyzer()
        self._tool_analyzer = ToolAnalyzer()
        
    def is_risky(self,mcp_name: str, server_config: Dict[str, Any], mcp_json_path: str) -> Tuple[float, Dict[str, float]]:
        args = server_config.get('args')
        market_place = None
        project_name = None
        logger.debug(f"Scanning MCP {mcp_name} with args: {args}")
        for i, arg in enumerate(args):
            if MarketPlaces.SMITHERY in arg:
                market_place = MarketPlaces.SMITHERY
                for j,arg in enumerate(args[i+1:]):
                    if "run" in arg:
                        project_name = args[i+j+2]
                        logger.debug(f"Project and market place: {project_name} and {market_place}")
                        break
        
        if market_place is None or project_name is None:
            if server_config.get("command") == "npx":
                for arg in args:
                    if not arg.startswith("-"):
                        project_name = arg
                        break
                if project_name is None:
                    logger.warning(f"MCP {mcp_name} is not supported. Skipping server.")
                    return False
                else:
                    market_place = MarketPlaces.NPM
                    
            else:
                logger.warning(f"MCP {mcp_name} is not supported. Skipping server.")
                return False
        logger.debug(f"Analyzing MCP {mcp_name} with market place {market_place} and project name {project_name}")
        final_score, component_scores = self._mcp_reputation_analyzer.analyze(market_place=market_place, project_name=project_name)
        if final_score <= 30:
            # self.edit_mcp_config_file(mcp_json_path, mcp_name, "blocked")
            return True
        return False
    
    def scan_mcps_reputation(self, proxied_server_configs: Dict[str, Any], mcp_json_path: str) -> GetewayContext:
        for name, server_config in proxied_server_configs.items():
            if server_config.get("blocked") != "skipped":
                if self.is_risky(mcp_name=name, server_config=server_config, mcp_json_path=mcp_json_path):
                    logger.warning(f"MCP {name} is risky and blocked")
                    if server_config.get("blocked") != "blocked":
                        proxied_server_configs[name]["blocked"] = "blocked"
                        self.edit_mcp_config_file(mcp_json_path, name, "blocked")
                elif server_config.get("blocked") == "blocked":
                    proxied_server_configs[name]["blocked"] = None
        return proxied_server_configs
        
    
    def scan_server_tools(self, context: GetewayContext) -> GetewayContext:
        for server_name, proxied_server in context.proxied_servers.items():
                if proxied_server.session:  # Only register for active sessions
                    if proxied_server.blocked != "skipped":    
                        for tool in proxied_server.list_tools():
                            tool_params_description = "\n".join(param[2] for param in get_tool_params_description(tool))
                            description = tool.description + "\n\n" + tool_params_description
                            tool_risks = self._tool_analyzer.is_description_safe(description)
                            
                            if not tool_risks.get("is_safe"):
                                logger.warning(f"MCP SERVER '{server_name}', TOOL '{tool.name}' has risks: {tool_risks.get("results")}")
                                logger.warning(f"MCP SERVER '{server_name}' is blocked")
                                context.proxied_servers[server_name].blocked = "blocked"
                                if context.proxied_servers[server_name].blocked != "blocked":
                                    self.edit_mcp_config_file(context.mcp_json_path, server_name, "blocked")
                                break
                            
                        if context.proxied_servers[server_name].blocked is None:
                            context.proxied_servers[server_name].blocked = "passed"
                            logger.info(f"MCP SERVER '{server_name}' is safe.")
                            self.edit_mcp_config_file(context.mcp_json_path, server_name, "passed")
                        elif context.proxied_servers[server_name].blocked == "passed":
                            logger.info(f"MCP SERVER '{server_name}' is safe.")
        return context
        
    def edit_mcp_config_file(self, mcp_json_path: str, server_name: str, blocked: str) -> None:
        logger.debug(f"Editing MCP config file {mcp_json_path} for server {server_name} with blocked status {blocked}")
        with open(mcp_json_path, 'r') as file:
            mcp_configuration = json.load(file)
        with open(mcp_json_path, 'w') as file:
            mcp_configuration["mcpServers"]["mcp-gateway"][Constants.SERVERS][server_name]["blocked"] = blocked
            json.dump(mcp_configuration, file, indent=4)


if __name__ == "__main__":
    scanner = Scanner()
    scanner.is_risky(mcp_name="test123", server_config={"args": ["--mcp-json-path", "~/.cursor/mcp.json", "--plugin", "basic", "--plugin", "xetrack", "--scan"]}, mcp_json_path="~/.cursor/mcp.json")
