import logging
from typing import Any, Dict, Optional, Tuple
from mcp import types

# Import PluginManager and PluginContext
from mcp_gateway.plugins.manager import PluginManager
from mcp_gateway.plugins.base import PluginContext

logger = logging.getLogger(__name__)


class SanitizationError(Exception):
    """Custom exception for critical sanitization failures raised by plugins."""

    pass


def _blocked_tool_result(message: str) -> types.CallToolResult:
    """Return a CallToolResult that does not forward upstream content."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        isError=True,
    )


# Note: These functions now act primarily as dispatchers to the PluginManager.
# The actual sanitization logic resides within the loaded plugins.


async def sanitize_request(
    plugin_manager: PluginManager,
    server_name: str,
    capability_type: str,
    name: str,
    arguments: Optional[Dict[str, Any]],
    mcp_context: Optional[
        Any
    ] = None,  # Pass MCP context if available/needed by plugins
) -> Optional[Dict[str, Any]]:
    """Runs request plugins for a capability call.

    Args:
        plugin_manager: The initialized PluginManager instance.
        server_name: The name of the target proxied server.
        capability_type: The type of capability ('tool', 'resource', 'prompt').
        name: The name of the capability.
        arguments: The arguments for the capability call.
        mcp_context: Optional MCP context.

    Returns:
        The sanitized arguments dictionary, or None if the request was blocked by a plugin.
    """
    logger.debug(f"Running request plugins for {server_name}/{capability_type}/{name}")
    context = PluginContext(
        server_name=server_name,
        capability_type=capability_type,
        capability_name=name,
        arguments=arguments,
        mcp_context=mcp_context,
    )
    try:
        sanitized_args = await plugin_manager.process_request(context)
        return sanitized_args
    except Exception as e:
        # Fail closed: block the request when request plugins error (#16).
        logger.error(
            f"Error running request plugins for {server_name}/{capability_type}/{name}: {e}",
            exc_info=True,
        )
        return None


async def sanitize_response(
    plugin_manager: PluginManager,
    server_name: str,
    capability_type: str,
    name: str,
    response: Any,  # Can be CallToolResult, Tuple[bytes, Optional[str]], etc.
    request_arguments: Optional[
        Dict[str, Any]
    ] = None,  # Provide request args for context
    mcp_context: Optional[Any] = None,
) -> Any:
    """Runs response plugins for a capability call result.

    Args:
        plugin_manager: The initialized PluginManager instance.
        server_name: The name of the source proxied server.
        capability_type: The type of capability ('tool', 'resource', 'prompt').
        name: The name of the capability.
        response: The response data received from the proxied server.
        request_arguments: Original arguments for the request (context for plugins).
        mcp_context: Optional MCP context.


    Returns:
        The sanitized response, potentially modified by plugins.

    Raises:
        SanitizationError: When response plugins fail or intentionally block.
    """
    logger.debug(f"Running response plugins for {server_name}/{capability_type}/{name}")
    context = PluginContext(
        server_name=server_name,
        capability_type=capability_type,
        capability_name=name,
        arguments=request_arguments,  # Pass original request args
        response=response,
        mcp_context=mcp_context,
    )
    try:
        sanitized_response = await plugin_manager.process_response(context)
        return sanitized_response
    except SanitizationError as se:
        # Allow specific SanitizationErrors from plugins to propagate
        logger.warning(
            f"SanitizationError from response plugin for {server_name}/{capability_type}/{name}: {se}"
        )
        raise se
    except Exception as e:
        # Fail closed (#16): never forward the unsanitized upstream response
        # when the plugin pipeline errors. Keep exception text in logs only —
        # SanitizationError may be mapped to client-facing tool results.
        logger.error(
            f"Error running response plugins for {server_name}/{capability_type}/{name}: {e}",
            exc_info=True,
        )
        raise SanitizationError(
            f"Response plugin execution failed for {server_name}/{capability_type}/{name}"
        ) from e


# --- Specific capability wrappers ---
# These can be simplified or potentially removed if the main Server methods
# call sanitize_request/sanitize_response directly with the correct capability_type.
# Keeping them for now for clearer separation.


async def sanitize_resource_read(
    plugin_manager: PluginManager,
    server_name: str,
    uri: str,  # Use URI as the 'name' for resources
    content: bytes,
    mime_type: Optional[str],
    mcp_context: Optional[Any] = None,
) -> Tuple[bytes, Optional[str]]:
    """Runs response plugins specifically for resource reads."""
    logger.debug(f"Sanitizing resource read for {server_name} resource {uri}")
    # Treat resource read as a 'response' phase
    response = (content, mime_type)
    sanitized_response = await sanitize_response(
        plugin_manager=plugin_manager,
        server_name=server_name,
        capability_type="resource",
        name=uri,  # Use URI as the capability name
        response=response,
        request_arguments={"uri": uri},  # Pass URI as argument context
        mcp_context=mcp_context,
    )
    # Ensure the response is still in the expected format (bytes, optional MIME).
    if (
        isinstance(sanitized_response, tuple)
        and len(sanitized_response) == 2
        and isinstance(sanitized_response[0], bytes)
        and (sanitized_response[1] is None or isinstance(sanitized_response[1], str))
    ):
        return sanitized_response
    else:
        logger.error(
            f"Response plugin for resource {uri} returned unexpected type {type(sanitized_response)}. Blocking."
        )
        raise SanitizationError(
            f"Response plugin for resource {uri} returned unexpected type"
        )


async def sanitize_tool_call_args(
    plugin_manager: PluginManager,
    server_name: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    mcp_context: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Runs request plugins specifically for tool calls."""
    logger.info(f"Sanitizing tool call args for {server_name} tool {tool_name}")
    return await sanitize_request(
        plugin_manager=plugin_manager,
        server_name=server_name,
        capability_type="tool",
        name=tool_name,
        arguments=arguments,
        mcp_context=mcp_context,
    )


async def sanitize_tool_call_result(
    plugin_manager: PluginManager,
    server_name: str,
    tool_name: str,
    result: types.CallToolResult,  # Expecting CallToolResult specifically here
    request_arguments: Optional[Dict[str, Any]] = None,
    mcp_context: Optional[Any] = None,
) -> types.CallToolResult:
    """Runs response plugins specifically for tool call results."""
    logger.info(f"Sanitizing tool call result for {server_name} tool {tool_name}")

    try:
        sanitized_result = await sanitize_response(
            plugin_manager=plugin_manager,
            server_name=server_name,
            capability_type="tool",
            name=tool_name,
            response=result,
            request_arguments=request_arguments,
            mcp_context=mcp_context,
        )
    except SanitizationError as se:
        # Client-facing text stays generic; details stay in logs only.
        logger.error(
            f"Sanitization blocked tool result for {server_name}/{tool_name}: {se}"
        )
        return _blocked_tool_result("Gateway policy violation")

    # Ensure the response is still a CallToolResult — never fail open to the
    # unsanitized upstream payload (#16).
    if isinstance(sanitized_result, types.CallToolResult):
        return sanitized_result

    logger.error(
        f"Response plugin for tool {tool_name} returned unexpected type "
        f"{type(sanitized_result)}. Blocking original result."
    )
    return _blocked_tool_result("Gateway policy violation")


# Removed old hardcoded sanitization logic for 'AI chip company roadmap' etc.
# That logic is now inside BasicGuardrailPlugin.process_response
