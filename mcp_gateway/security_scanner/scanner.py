import json
import logging
import os  # Added for path expansion and directory creation
from pathlib import Path  # Added for path manipulation
from mcp_gateway.config import Constants, get_tool_params_description
from mcp_gateway.security_scanner.config import MarketPlaces, logger
from mcp_gateway.security_scanner.project_analyzer import ProjectAnalyzer
from mcp_gateway.security_scanner.tool_poisoning_analyzer import ToolAnalyzer
from mcp_gateway.server import GetewayContext
from typing import Tuple, Dict, List, Any


class Scanner:
    def __init__(self):
        self._mcp_reputation_analyzer = ProjectAnalyzer()
        self._tool_analyzer = ToolAnalyzer()

    def is_risky(
        self, mcp_name: str, server_config: Dict[str, Any], mcp_json_path: str
    ) -> bool:
        """
        Determines if an MCP server is risky based on its reputation score.

        Args:
            mcp_name: The name of the MCP server
            server_config: The server configuration dictionary
            mcp_json_path: Path to the MCP configuration file

        Returns:
            bool: True if the MCP is risky and should be blocked, False otherwise
        """
        args = server_config.get("args", [])
        market_place = None
        project_name = None

        logger.debug(f"Scanning MCP {mcp_name} with args: {args}")

        # Check for Smithery marketplace
        for i, arg in enumerate(args):
            if MarketPlaces.SMITHERY in arg:
                market_place = MarketPlaces.SMITHERY
                # Look for the project name after "run" argument
                for j, next_arg in enumerate(args[i + 1 :], start=i + 1):
                    if "run" in next_arg and j + 1 < len(args):
                        project_name = args[j + 1]
                        logger.debug(f"Found Smithery project: {project_name}")
                        break
                break

        # Check for NPM marketplace if not Smithery
        if market_place is None or project_name is None:
            if server_config.get("command") == "npx":
                # Find the first non-flag argument as the package name
                for arg in args:
                    if not arg.startswith("-"):
                        project_name = arg
                        market_place = MarketPlaces.NPM
                        logger.debug(f"Found NPM project: {project_name}")
                        break

                if project_name is None:
                    logger.warning(
                        f"MCP {mcp_name} is NPX but no package name found. Skipping server."
                    )
                    return False
            else:
                logger.warning(
                    f"MCP {mcp_name} is not supported marketplace. Skipping server."
                )
                return False

        if market_place is None or project_name is None:
            logger.warning(
                f"Could not determine marketplace or project name for {mcp_name}. Skipping server."
            )
            return False

        try:
            logger.debug(
                f"Analyzing MCP {mcp_name} with marketplace {market_place} and project name {project_name}"
            )
            final_score, component_scores = self._mcp_reputation_analyzer.analyze(
                market_place=market_place, project_name=project_name
            )

            logger.info(f"MCP {mcp_name} reputation score: {final_score}")

            # Consider risky if score is below threshold
            is_risky = final_score <= 30

            if is_risky:
                logger.warning(f"MCP {mcp_name} is risky with score {final_score}")
            else:
                logger.info(f"MCP {mcp_name} is safe with score {final_score}")

            return is_risky

        except Exception as e:
            logger.error(f"Error analyzing MCP {mcp_name}: {e}")
            # In case of error, consider it risky for safety
            return True

    def scan_mcps_reputation(
        self, proxied_server_configs: Dict[str, Any], mcp_json_path: str
    ) -> Dict[str, Any]:
        """
        Scan all MCP servers for reputation issues.

        Args:
            proxied_server_configs: Dictionary of server configurations
            mcp_json_path: Path to the MCP configuration file

        Returns:
            Dict[str, Any]: Updated server configurations with blocking status
        """
        for name, server_config in proxied_server_configs.items():
            # Skip if already marked as skipped
            if server_config.get("blocked") == "skipped":
                continue

            try:
                if self.is_risky(
                    mcp_name=name,
                    server_config=server_config,
                    mcp_json_path=mcp_json_path,
                ):
                    logger.warning(f"MCP {name} is risky and will be blocked")
                    # Only update if not already blocked
                    if server_config.get("blocked") != "blocked":
                        proxied_server_configs[name]["blocked"] = "blocked"
                        self.edit_mcp_config_file(mcp_json_path, name, "blocked")
                else:
                    # If it was previously blocked but now safe, unblock it
                    if server_config.get("blocked") == "blocked":
                        proxied_server_configs[name]["blocked"] = None
                        logger.info(f"MCP {name} is now safe, unblocking")

            except Exception as e:
                logger.error(f"Error scanning MCP {name}: {e}")
                # In case of error, block for safety
                proxied_server_configs[name]["blocked"] = "blocked"
                self.edit_mcp_config_file(mcp_json_path, name, "blocked")

        return proxied_server_configs

    def scan_server_tools(self, context: GetewayContext) -> GetewayContext:
        """
        Scan all server tools for security issues.

        Args:
            context: The gateway context containing server information

        Returns:
            GetewayContext: Updated context with blocking status
        """
        for server_name, proxied_server in context.proxied_servers.items():
            # Only scan servers with active sessions
            if not proxied_server.session:
                continue

            # Skip if already marked as skipped
            if proxied_server.blocked == "skipped":
                continue

            try:
                # Check each tool in the server
                for tool in proxied_server.list_tools():
                    tool_params_description = "\n".join(
                        param[2] for param in get_tool_params_description(tool)
                    )
                    description = tool.description + "\n\n" + tool_params_description
                    tool_risks = self._tool_analyzer.is_description_safe(description)

                    if not tool_risks.get("is_safe"):
                        logger.warning(
                            f"MCP SERVER '{server_name}', TOOL '{tool.name}' has risks: {tool_risks.get('results')}"
                        )
                        logger.warning(
                            f"MCP SERVER '{server_name}' is blocked due to risky tool"
                        )

                        # Block the server and update config
                        context.proxied_servers[server_name].blocked = "blocked"
                        self.edit_mcp_config_file(
                            context.mcp_json_path, server_name, "blocked"
                        )
                        break
                else:
                    # All tools are safe
                    if context.proxied_servers[server_name].blocked is None:
                        context.proxied_servers[server_name].blocked = "passed"
                        logger.info(f"MCP SERVER '{server_name}' is safe.")
                        self.edit_mcp_config_file(
                            context.mcp_json_path, server_name, "passed"
                        )
                    elif context.proxied_servers[server_name].blocked == "passed":
                        logger.info(f"MCP SERVER '{server_name}' remains safe.")

            except Exception as e:
                logger.error(f"Error scanning tools for server {server_name}: {e}")
                # In case of error, block for safety
                context.proxied_servers[server_name].blocked = "blocked"
                self.edit_mcp_config_file(context.mcp_json_path, server_name, "blocked")

        return context

    def edit_mcp_config_file(
        self, mcp_json_path: str, server_name: str, blocked: str
    ) -> None:
        """
        Edit the MCP configuration file to update the blocked status.

        Args:
            mcp_json_path: Path to the MCP configuration file
            server_name: Name of the server to update
            blocked: New blocked status
        """
        logger.debug(
            f"Editing MCP config file {mcp_json_path} for server {server_name} with blocked status {blocked}"
        )

        try:
            # Expand user path
            expanded_path = os.path.expanduser(mcp_json_path)

            with open(expanded_path, "r") as file:
                mcp_configuration = json.load(file)

            # Update the blocked status
            if (
                Constants.SERVERS
                in mcp_configuration.get("mcpServers", {}).get("mcp-gateway", {})
                and server_name
                in mcp_configuration["mcpServers"]["mcp-gateway"][Constants.SERVERS]
            ):
                mcp_configuration["mcpServers"]["mcp-gateway"][Constants.SERVERS][
                    server_name
                ]["blocked"] = blocked

                with open(expanded_path, "w") as file:
                    json.dump(mcp_configuration, file, indent=4)

                logger.debug(
                    f"Successfully updated blocked status for {server_name} to {blocked}"
                )
            else:
                logger.warning(
                    f"Could not find server {server_name} in configuration file"
                )

        except Exception as e:
            logger.error(f"Error editing MCP config file: {e}")


if __name__ == "__main__":
    scanner = Scanner()
    # Example test - should be moved to proper test file
    result = scanner.is_risky(
        mcp_name="test123",
        server_config={
            "args": [
                "--mcp-json-path",
                "~/.cursor/mcp.json",
                "--plugin",
                "basic",
                "--plugin",
                "xetrack",
                "--scan",
            ]
        },
        mcp_json_path="~/.cursor/mcp.json",
    )
    print(f"Is risky: {result}")
