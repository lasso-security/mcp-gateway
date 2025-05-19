import asyncio
import logging
import os
import argparse
import sys
from contextlib import asynccontextmanager
from typing import (
    Any,
    Dict,
    AsyncIterator,
    List,
    Tuple,
)
import inspect

from mcp.server.fastmcp import FastMCP, Context
from mcp import types

from mcp_gateway.config import load_config, get_tool_params_description
from mcp_gateway.sanitizers import SanitizationError
from mcp_gateway.plugins.manager import PluginManager
from mcp_gateway.security_scanner.scanner import Scanner
from mcp_gateway.server import GetewayContext, Server
# --- Global Config for Args ---
cli_args = None
log_level = os.environ.get("LOGLEVEL", "INFO").upper()

# Configure logging
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Dynamic Capability Registration ---
async def register_dynamic_tool(
    gateway_mcp: FastMCP,
    server_name: str,
    tool: types.Tool,
    proxied_server: Server,
    plugin_manager: PluginManager,
):
    """Registers a dynamic tool handler directly with the FastMCP instance."""
    dynamic_tool_name = f"{server_name}_{tool.name}"
    logger.debug(f"Attempting to register dynamic tool: {dynamic_tool_name}")

    # Extract parameter types from the tool's inputSchema
    param_signatures = get_tool_params_description(tool)# Create a properly typed dynamic function based on the original tool's signature
    def create_typed_handler(param_signatures):
        # Create parameters for the function signature
        parameters = [
            inspect.Parameter(
                name="ctx",
                annotation=Context,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        annotations = {"ctx": Context, "return": types.CallToolResult}

        # Add parameters from the original tool
        for name, type_ann, description in param_signatures:
            parameters.append(
                inspect.Parameter(
                    name=name,
                    annotation=type_ann,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            )
            annotations[name] = type_ann

        # Create the proper signature
        sig = inspect.Signature(parameters=parameters)

        # Define the handler with the proper signature
        async def dynamic_tool_impl(*args, **kwargs):
            ctx = kwargs.get("ctx", args[0] if args else None)
            # Remove ctx from kwargs before passing to the proxied server
            tool_kwargs = {k: v for k, v in kwargs.items() if k != "ctx"}

            logger.info(
                f"Executing dynamic tool '{dynamic_tool_name}' (proxied from {server_name}/{tool.name})"
            )
            try:
                result = await proxied_server.call_tool(
                    plugin_manager=plugin_manager,
                    name=tool.name,
                    arguments=tool_kwargs,
                    mcp_context=ctx,  # Pass gateway context
                )
                return result
            except SanitizationError as se:
                logger.error(
                    f"Sanitization policy violation for dynamic tool '{dynamic_tool_name}': {se}"
                )
                return types.CallToolResult(
                    outputs=[
                        {"type": "error", "message": f"Gateway policy violation: {se}"}
                    ]
                )
            except Exception as e:
                logger.error(
                    f"Error executing dynamic tool '{dynamic_tool_name}': {e}",
                    exc_info=True,
                )
                return types.CallToolResult(
                    outputs=[
                        {
                            "type": "error",
                            "message": f"Error executing dynamic tool '{dynamic_tool_name}': {e}",
                        }
                    ]
                )

        # Apply the signature to the function
        dynamic_tool_impl.__signature__ = sig
        dynamic_tool_impl.__annotations__ = annotations

        return dynamic_tool_impl

    # Create the handler with proper signature
    dynamic_tool_impl = create_typed_handler(param_signatures)

    # Set metadata properties for FastMCP
    dynamic_tool_impl.__name__ = dynamic_tool_name
    dynamic_tool_impl.__doc__ = tool.description or f"Proxied tool from {server_name}"

    # Register with FastMCP
    try:
        # Use the full schema to register
        tool_decorator = gateway_mcp.tool(
            name=dynamic_tool_name, description=tool.description
        )
        tool_decorator(dynamic_tool_impl)
        logger.info(f"Registered dynamic tool '{dynamic_tool_name}' with FastMCP")
    except Exception as e:
        logger.error(
            f"Failed to register dynamic tool {dynamic_tool_name} with FastMCP: {e}",
            exc_info=True,
        )


async def register_dynamic_prompt(
    gateway_mcp: FastMCP,
    server_name: str,
    prompt: types.Prompt,
    proxied_server: Server,
    plugin_manager: PluginManager,
):
    """Registers a dynamic prompt handler directly with the FastMCP instance."""
    dynamic_prompt_name = f"{server_name}_{prompt.name}"
    logger.debug(f"Attempting to register dynamic prompt: {dynamic_prompt_name}")

    # Extract parameter types from the prompt's arguments
    param_signatures = []
    if hasattr(prompt, "arguments") and prompt.arguments:
        for arg in prompt.arguments:
            param_type = str  # Default type for prompt arguments is string
            description = getattr(arg, "description", None)

            param_signatures.append((arg.name, param_type, description))

    # Create a properly typed dynamic function based on the original prompt's signature
    def create_typed_handler(param_signatures):
        # Create parameters for the function signature
        parameters = [
            inspect.Parameter(
                name="ctx",
                annotation=Context,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        annotations = {"ctx": Context, "return": types.GetPromptResult}

        # Add parameters from the original prompt
        for name, type_ann, description in param_signatures:
            parameters.append(
                inspect.Parameter(
                    name=name,
                    annotation=type_ann,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            )
            annotations[name] = type_ann

        # Create the proper signature
        sig = inspect.Signature(parameters=parameters)

        # Define the handler with the proper signature
        async def dynamic_prompt_impl(*args, **kwargs):
            ctx = kwargs.get("ctx", args[0] if args else None)
            # Remove ctx from kwargs before passing to the proxied server
            prompt_kwargs = {k: v for k, v in kwargs.items() if k != "ctx"}

            logger.info(
                f"Executing dynamic prompt '{dynamic_prompt_name}' (proxied from {server_name}/{prompt.name})"
            )
            try:
                result = await proxied_server.get_prompt(
                    plugin_manager=plugin_manager,
                    name=prompt.name,
                    arguments=prompt_kwargs,
                    mcp_context=ctx,  # Pass gateway context
                )
                return result  # Server.get_prompt already wraps sanitization errors
            except Exception as e:
                logger.error(
                    f"Error executing dynamic prompt '{dynamic_prompt_name}': {e}",
                    exc_info=True,
                )
                return types.GetPromptResult(
                    messages=[
                        types.PromptMessage(
                            role="assistant",
                            content=types.TextContent(
                                type="text",
                                text=f"Error executing prompt '{dynamic_prompt_name}': {e}",
                            ),
                        )
                    ]
                )

        # Apply the signature to the function
        dynamic_prompt_impl.__signature__ = sig
        dynamic_prompt_impl.__annotations__ = annotations

        return dynamic_prompt_impl

    # Create the handler with proper signature
    dynamic_prompt_impl = create_typed_handler(param_signatures)

    # Set metadata properties for FastMCP
    dynamic_prompt_impl.__name__ = dynamic_prompt_name
    dynamic_prompt_impl.__doc__ = (
        prompt.description or f"Proxied prompt from {server_name}"
    )

    # Register with FastMCP
    try:
        prompt_decorator = gateway_mcp.prompt(
            name=dynamic_prompt_name, description=prompt.description
        )
        prompt_decorator(dynamic_prompt_impl)
        logger.info(f"Registered dynamic prompt '{dynamic_prompt_name}' with FastMCP")
    except Exception as e:
        logger.error(
            f"Failed to register dynamic prompt {dynamic_prompt_name} with FastMCP: {e}",
            exc_info=True,
        )


async def register_proxied_capabilities(gateway_mcp: FastMCP, context: GetewayContext):
    """Fetches capabilities from proxied servers and registers them dynamically with the gateway_mcp."""
    logger.info("Dynamically registering capabilities from proxied servers...")
    plugin_manager = context.plugin_manager
    if not plugin_manager:
        logger.error(
            "PluginManager missing during dynamic registration. Cannot register."
        )
        return

    registration_tasks = []
    registered_tool_count = 0
    registered_prompt_count = 0
    
    if cli_args and cli_args.scan:
        scanner = Scanner()
        context = scanner.scan_server_tools(context)
    
    for server_name, proxied_server in context.proxied_servers.items():
        if proxied_server.blocked == "blocked":
            logger.warning(f"Server '{server_name}' is blocked. Skipping server.")
            await proxied_server.stop()
            continue
        if proxied_server.session:  # Only register for active sessions
            # Register tools for this server
            for tool in proxied_server._tools:  # Use cached list
                registration_tasks.append(
                    register_dynamic_tool(
                        gateway_mcp,  # Pass FastMCP instance
                        server_name,
                        tool,
                        proxied_server,
                        plugin_manager,
                    )
                )
                registered_tool_count += 1
            # Register prompts for this server
            for prompt in proxied_server._prompts:  # Use cached list
                registration_tasks.append(
                    register_dynamic_prompt(
                        gateway_mcp,  # Pass FastMCP instance
                        server_name,
                        prompt,
                        proxied_server,
                        plugin_manager,
                    )
                )
                registered_prompt_count += 1
            # Note: Dynamic resource registration is deferred
            if proxied_server._resources:
                logger.warning(
                    f"Dynamic resource registration for server '{server_name}' is not yet implemented. Resources will not be exposed via gateway."
                )
        else:
            logger.warning(
                f"Skipping dynamic registration for inactive server: {server_name}"
            )

    if registration_tasks:
        await asyncio.gather(*registration_tasks)
        logger.info(
            f"Dynamic registration process complete. Attempted to register {registered_tool_count} tools and {registered_prompt_count} prompts with FastMCP."
        )
    else:
        logger.info("No active proxied servers found or no capabilities to register.")


# --- Lifespan Management ---


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[GetewayContext]:
    """Manages the lifecycle of proxied MCP servers and dynamic registration."""
    global cli_args
    logger.info("MCP gateway lifespan starting...")

    # Initialize plugin categories
    enabled_plugin_types = []
    enabled_plugins = {}

    # Handle the unified plugin parameter and plugin type discovery
    if cli_args and cli_args.plugin:
        # Import the necessary functions from the plugin manager
        from mcp_gateway.plugins.manager import get_plugin_type, discover_plugins

        # Ensure plugins are discovered
        discover_plugins()

        for plugin_name in cli_args.plugin:
            # Get the plugin type using the plugin name
            plugin_type = get_plugin_type(plugin_name)

            if plugin_type:
                # Add to appropriate category
                if plugin_type not in enabled_plugin_types:
                    enabled_plugin_types.append(plugin_type)
                    enabled_plugins[plugin_type] = []

                # Add the plugin to its type list (handle potential duplicates)
                if plugin_name not in enabled_plugins[plugin_type]:
                    enabled_plugins[plugin_type].append(plugin_name)
                    logger.info(f"Enabling {plugin_type} plugin: {plugin_name}")
            else:
                logger.warning(
                    f"Unknown plugin: {plugin_name} - could not determine plugin type"
                )

    # Log plugin status
    if "guardrail" in enabled_plugin_types:
        logger.info(
            f"Guardrail plugins ENABLED: {enabled_plugins.get('guardrail', [])}"
        )
    else:
        logger.info("Guardrail plugins DISABLED.")

    if "tracing" in enabled_plugin_types:
        logger.info(f"Tracing plugins ENABLED: {enabled_plugins.get('tracing', [])}")
    else:
        logger.info("Tracing plugins DISABLED.")

    # Initialize plugin manager with configuration
    plugin_manager = PluginManager(
        enabled_types=enabled_plugin_types, enabled_plugins=enabled_plugins
    )

    # Load proxied server configs
    proxied_server_configs = load_config(cli_args.mcp_json_path)

    # Initialize context
    context = GetewayContext(plugin_manager=plugin_manager, mcp_json_path=cli_args.mcp_json_path)

    # Create Server instances but don't start them yet
    if cli_args and cli_args.scan:
        scanner = Scanner()
        proxied_server_configs = scanner.scan_mcps_reputation(proxied_server_configs, cli_args.mcp_json_path)
    
    for name, server_config in proxied_server_configs.items():
        if server_config.get("blocked") == "blocked":
            logger.warning(f"Server '{name}' is blocked. Skipping server.")
            continue
        
        proxied_server = Server(name, server_config)        
        context.proxied_servers.update({name: proxied_server})

    # Start all servers concurrently
    if context.proxied_servers:
        logger.info("Starting all configured proxied servers...")
        start_tasks = [
            asyncio.create_task(server.start())
            for server in context.proxied_servers.values()
        ]
        if start_tasks:
            results = await asyncio.gather(*start_tasks, return_exceptions=True)
            # Check results for errors during startup
            failed_servers = []
            for i, result in enumerate(results):
                server_name = list(context.proxied_servers.keys())[i]
                if isinstance(result, Exception):
                    logger.error(
                        f"Failed to start server '{server_name}' during gather: {result}",
                        exc_info=result if logger.isEnabledFor(logging.DEBUG) else None,
                    )
                    failed_servers.append(server_name)
                else:
                    logger.info(f"Successfully started server '{server_name}'.")

            # Remove failed servers from context so we don't try to register them
            for name in failed_servers:
                context.proxied_servers.pop(name, None)

            logger.info("Attempted to start all configured proxied servers.")
    else:
        logger.warning(
            "No proxied MCP servers configured. Running in standalone mode (plugins still active)."
        )

    # Register capabilities from proxied servers
    await register_proxied_capabilities(server, context)

    try:
        # Yield the context containing servers and plugin manager
        yield context
    finally:
        logger.info("MCP gateway lifespan shutting down...")
        # Stop only the servers that were successfully started
        stop_tasks = [
            asyncio.create_task(server.stop())
            for name, server in context.proxied_servers.items()
            if server._session is not None  # Check if session was ever active
        ]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
            logger.info("All active proxied servers stopped.")
        logger.info("MCP gateway shutdown complete.")


# Initialize the MCP gateway server
# Pass description and version if desired
mcp = FastMCP("MCP Gateway", lifespan=lifespan, version="1.0.0")


# --- Gateway's Own Capability Implementations ---


@mcp.tool()  # Keep get_metadata as it provides original server details
async def get_metadata(ctx: Context) -> Dict[str, Any]:
    """Provides metadata about all available proxied MCPs, including their original capabilities."""
    geteway_context: GetewayContext = ctx.request_context.lifespan_context
    metadata: Dict[str, Any] = {}

    if not geteway_context.proxied_servers:
        return {"status": "standalone_mode", "message": "No proxied MCPs configured"}

    # Iterate through potentially *all* configured servers, even if start failed, to report status
    all_configured_servers = load_config(
        cli_args.mcp_json_path if cli_args else None
    )  # Reload to get names if needed
    if not all_configured_servers:
        all_configured_servers = {}  # Handle case where config path is missing

    for name in all_configured_servers.keys():
        server = geteway_context.proxied_servers.get(name)
        server_metadata: Dict[str, Any] = {
            "status": "inactive",
            "capabilities": None,
            "original_tools": [],
            "original_resources": [],
            "original_prompts": [],
        }

        if not server or not server.session:
            server_metadata["error"] = "Server session not active or start failed"
            metadata[name] = server_metadata
            continue

        try:
            server_metadata["status"] = "active"
            # 1. Get Capabilities
            capabilities = (
                await server.get_capabilities()
            )  # Use the stored capabilities
            server_metadata["capabilities"] = (
                capabilities.model_dump() if capabilities else None
            )

            # 2. List Original Tools (use cached list)
            if capabilities and capabilities.tools:
                server_metadata["original_tools"] = [
                    tool.model_dump() for tool in server._tools
                ]
            else:
                logger.debug(
                    f"Server '{name}' does not support tools, skipping list_tools in metadata."
                )

            # 3. List Original Resources (use cached list)
            if capabilities and capabilities.resources:
                server_metadata["original_resources"] = [
                    res.model_dump() for res in server._resources
                ]
            else:
                logger.debug(
                    f"Server '{name}' does not support resources, skipping list_resources in metadata."
                )

            # 4. List Original Prompts (use cached list)
            if capabilities and capabilities.prompts:
                server_metadata["original_prompts"] = [
                    p.model_dump() for p in server._prompts
                ]
            else:
                logger.debug(
                    f"Server '{name}' does not support prompts, skipping list_prompts in metadata."
                )

            metadata[name] = server_metadata

        except Exception as e:
            # Catch general errors during metadata retrieval for this specific server
            logger.error(
                f"General error getting metadata for server '{name}': {e}",
                exc_info=True,
            )
            metadata[name] = {
                "status": "error",
                "error": f"Failed to retrieve metadata: {e}",
                "capabilities": server_metadata.get(
                    "capabilities"
                ),  # Include caps if fetched before error
                "original_tools": server_metadata.get("original_tools", []),
                "original_resources": server_metadata.get("original_resources", []),
                "original_prompts": server_metadata.get("original_prompts", []),
            }

    return metadata


# --- Argument Parsing & Main ---
def parse_args(args=None):
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="MCP Gateway Server")
    parser.add_argument(
        "--mcp-json-path",
        type=str,
        required=True,
        help="Path to the mcp.json configuration file",
    )
    # Add unified plugin parameter
    parser.add_argument(
        "-p",
        "--plugin",
        action="append",
        help="Enable specific plugins (e.g., 'basic', 'lasso', 'xetrack'). Multiple plugins can be enabled by repeating the argument.",
        default=[],
    )
    # Keep backward compatibility
    parser.add_argument(
        "--enable-guardrails",
        action="append",
        help="[DEPRECATED] Enable specific guardrail plugins. Use --plugin instead.",
        nargs="?",
        const="all",
        default=[],
    )
    parser.add_argument(
        "--enable-tracing",
        action="append",
        help="[DEPRECATED] Enable specific tracing plugins. Use --plugin instead.",
        nargs="?",
        const="all",
        default=[],
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Enable security scanner.",
    )
    if args is None:
        args = sys.argv[1:]

    parsed_args = parser.parse_args(args)

    # Debug print for scan parameter
    logger.info(f"Security scanner: {'enabled' if parsed_args.scan else 'disabled'}")

    # Simplify backward compatibility by adding enable-guardrails and enable-tracing values to plugin list
    for guardrail in parsed_args.enable_guardrails:
        if guardrail and guardrail not in parsed_args.plugin:
            parsed_args.plugin.append(guardrail)
            logger.info(f"Adding backward compatibility guardrail plugin: {guardrail}")

    for tracing in parsed_args.enable_tracing:
        if tracing and tracing not in parsed_args.plugin:
            parsed_args.plugin.append(tracing)
            logger.info(f"Adding backward compatibility tracing plugin: {tracing}")

    return parsed_args


def main():
    global cli_args
    cli_args = parse_args()

    logger.info("Starting MCP gateway server directly...")
    mcp.run()


if __name__ == "__main__":
    main()