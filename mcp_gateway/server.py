# server.py
import asyncio
import logging
import os
import json
import argparse
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    AsyncIterator,
    List,
    Optional,
    Tuple,
    Literal,
)
import inspect

from mcp.server.fastmcp import Context
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from mcp_gateway.sanitizers import (
    SanitizationError,
    sanitize_tool_call_args,
    sanitize_tool_call_result,
    sanitize_resource_read,
    sanitize_response,
)
from mcp_gateway.plugins.manager import PluginManager

# --- Global Config for Args ---
cli_args = None
log_level = os.environ.get("LOGLEVEL", "INFO").upper()

# Configure logging
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Server:
    """Manages the connection and interaction with a single proxied MCP server."""

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initializes the Proxied Server.

        Args:
            name: The unique name identifier for this server.
            config: The configuration dictionary for this server (command, args, env).
        """
        self.name = name
        self.config = config
        self._session: Optional[ClientSession] = None
        self._client_cm: Optional[
            AsyncIterator[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]
        ] = None
        self._server_info: Optional[types.InitializeResult] = None
        self._exit_stack = AsyncExitStack()
        # Store fetched capabilities for easier access later
        self._tools: List[types.Tool] = []
        self._resources: List[types.Resource] = []
        self._prompts: List[types.Prompt] = []
        logger.info(f"Initialized Proxied Server: {self.name}")

    @property
    def blocked(self) -> Literal["blocked", "skipped", "passed", None]:
        return self.config.get("blocked")

    @blocked.setter
    def blocked(self, value: Literal["blocked", "skipped", "passed", None]):
        self.config["blocked"] = value

    @property
    def session(self) -> ClientSession:
        """Returns the active ClientSession, raising an error if not started."""
        if self._session is None:
            raise RuntimeError(f"Server '{self.name}' session not started.")
        return self._session

    async def start(self) -> None:
        """Starts the underlying MCP server process, establishes a client session,
        and fetches initial capabilities."""
        if self._session is not None:
            logger.warning(f"Server '{self.name}' already started.")
            return

        logger.info(f"Starting proxied server: {self.name}...")
        try:
            server_params = StdioServerParameters(
                command=self.config.get("command", ""),
                args=self.config.get("args", []),
                env=self.config.get("env", None),
            )

            # Use AsyncExitStack to manage the stdio_client context
            self._client_cm = stdio_client(server_params)
            read, write = await self._exit_stack.enter_async_context(self._client_cm)

            # Use AsyncExitStack to manage the ClientSession context
            session_cm = ClientSession(read, write)
            self._session = await self._exit_stack.enter_async_context(session_cm)

            # Capture and store the InitializeResult
            self._server_info = await self._session.initialize()
            logger.info(
                f"Proxied server '{self.name}' started and initialized successfully."
            )

            # Fetch and store initial lists of tools, resources, prompts
            await self._fetch_initial_capabilities()

        except Exception as e:
            logger.error(f"Failed to start server '{self.name}': {e}", exc_info=True)
            self._server_info = None  # Ensure server_info is None on failure
            await self.stop()  # Attempt cleanup if start failed
            raise

    async def _fetch_initial_capabilities(self):
        """Fetches and stores the initial lists of tools, resources, and prompts."""
        if not self.session:
            logger.warning(
                f"Cannot fetch capabilities for {self.name}, session inactive."
            )
            return

        try:
            # Fetch tools, resources, prompts simultaneously
            tools_res, resources_res, prompts_res = await asyncio.gather(
                self.session.list_tools(),
                self.session.list_resources(),
                self.session.list_prompts(),
                return_exceptions=True,
            )

            # Process Tools
            if isinstance(tools_res, Exception):
                logger.debug(f"Failed to list tools for {self.name}: {tools_res}")
                self._tools = []
            else:
                self._tools = self._extract_list(tools_res, "tools", types.Tool)

            # Process Resources
            if isinstance(resources_res, Exception):
                logger.debug(
                    f"Failed to list resources for {self.name}: {resources_res}"
                )
                self._resources = []
            else:
                self._resources = self._extract_list(
                    resources_res, "resources", types.Resource
                )

            # Process Prompts
            if isinstance(prompts_res, Exception):
                logger.debug(f"Failed to list prompts for {self.name}: {prompts_res}")
                self._prompts = []
            else:
                self._prompts = self._extract_list(prompts_res, "prompts", types.Prompt)

            logger.info(
                f"Fetched initial capabilities for {self.name}: "
                f"{len(self._tools)} tools, "
                f"{len(self._resources)} resources, "
                f"{len(self._prompts)} prompts."
            )

        except Exception as e:
            logger.error(
                f"Unexpected error fetching capabilities for {self.name}: {e}",
                exc_info=True,
            )
            self._tools, self._resources, self._prompts = [], [], []

    def _extract_list(
        self, result: Any, attribute_name: str, expected_type: type
    ) -> List[Any]:
        """Helper to extract list of items from potentially structured MCP results."""
        if hasattr(result, attribute_name):
            items = getattr(result, attribute_name)
        elif isinstance(result, list):
            items = result
        else:
            logger.warning(
                f"Unexpected result type {type(result)} when extracting {attribute_name} for {self.name}"
            )
            return []

        if isinstance(items, list):
            # Basic check if items are of the expected type (or can be treated as such)
            # More robust validation could be added here if needed
            return [item for item in items if isinstance(item, expected_type)]
        else:
            logger.warning(
                f"Extracted items for {attribute_name} is not a list for {self.name}: {type(items)}"
            )
            return []

    async def stop(self) -> None:
        """Stops the underlying MCP server process and closes the client session."""
        logger.info(f"Stopping proxied server: {self.name}...")
        await self._exit_stack.aclose()
        self._session = None
        self._client_cm = None
        self._server_info = None  # Clear server info on stop
        self._tools, self._resources, self._prompts = [], [], []  # Clear cached caps
        logger.info(f"Proxied server '{self.name}' stopped.")

    # --- MCP Interaction Methods (called by dynamic handlers) ---

    async def list_prompts(self) -> List[types.Prompt]:
        """Lists available prompts from the proxied server (uses cached list)."""
        # Return the cached list fetched during startup/refresh
        # For full dynamic support (listChanged), this would need to re-fetch
        return self._prompts

    async def get_prompt(
        self,
        plugin_manager: PluginManager,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
        mcp_context: Optional[Context] = None,
    ) -> types.GetPromptResult:
        """Gets a specific prompt from the proxied server, processing through plugins."""
        logger.info(f"Getting prompt {self.name}/{name} with arguments {arguments}")

        # Use original arguments for the actual call
        result = await self.session.get_prompt(name, arguments=arguments)

        # Sanitize Response
        # Note: sanitize_response is designed generically. Ensure it handles GetPromptResult.
        try:
            sanitized_result = await sanitize_response(
                plugin_manager=plugin_manager,
                server_name=self.name,
                capability_type="prompt",
                name=name,
                response=result,
                request_arguments=arguments,
                mcp_context=mcp_context,  # Pass gateway context
            )

            # Ensure the result is still the correct type
            if isinstance(sanitized_result, types.GetPromptResult):
                return sanitized_result
            else:
                logger.error(
                    f"Response plugin for prompt {self.name}/{name} returned unexpected type {type(sanitized_result)}. Returning original."
                )
                return result  # Or potentially craft an error GetPromptResult
        except SanitizationError as se:
            logger.error(
                f"Sanitization error processing prompt response for {self.name}/{name}: {se}"
            )
            # Return an error message within the GetPromptResult structure
            return types.GetPromptResult(
                messages=[
                    types.PromptMessage(
                        role="assistant",
                        content=types.TextContent(
                            type="text", text=f"Gateway policy violation: {se}"
                        ),
                    )
                ]
            )
        except Exception as e:
            logger.error(
                f"Error processing prompt response for {self.name}/{name}: {e}",
                exc_info=True,
            )
            return types.GetPromptResult(
                messages=[
                    types.PromptMessage(
                        role="assistant",
                        content=types.TextContent(
                            type="text", text=f"Error processing prompt response: {e}"
                        ),
                    )
                ]
            )

    async def list_resources(self) -> List[types.Resource]:
        """Lists available resources from the proxied server (uses cached list)."""
        return self._resources

    async def read_resource(
        self,
        plugin_manager: PluginManager,
        uri: str,
        mcp_context: Optional[Context] = None,
    ) -> Tuple[bytes, Optional[str]]:
        """Reads a resource from the proxied server after processing through plugins."""
        # No request args to sanitize for read_resource itself

        content, mime_type = await self.session.read_resource(uri)

        # Sanitize the response content using the dedicated function
        sanitized_content, sanitized_mime_type = await sanitize_resource_read(
            plugin_manager=plugin_manager,
            server_name=self.name,
            uri=uri,
            content=content,
            mime_type=mime_type,
            mcp_context=mcp_context,  # Pass gateway context
        )
        return sanitized_content, sanitized_mime_type

    def list_tools(self) -> List[types.Tool]:
        """Lists available tools from the proxied server (uses cached list)."""
        return self._tools

    async def call_tool(
        self,
        plugin_manager: PluginManager,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        mcp_context: Optional[Context] = None,
    ) -> types.CallToolResult:
        """Calls a tool on the proxied server after processing args and result through plugins."""
        logger.debug(f"Calling tool {self.name}/{name}")
        # 1. Sanitize request arguments
        sanitized_args = await sanitize_tool_call_args(
            plugin_manager=plugin_manager,
            server_name=self.name,
            tool_name=name,
            arguments=arguments,
            mcp_context=mcp_context,  # Pass gateway context
        )

        if sanitized_args is None:
            # Handle blocked request appropriately
            logger.warning(
                f"Tool call {self.name}/{name} blocked by request sanitizer plugin."
            )
            # Raise specific error to be caught by dynamic handler
            raise SanitizationError(
                f"Request blocked by gateway policy for tool '{self.name}/{name}'."
            )

        # 2. Call the tool with sanitized arguments
        result = await self.session.call_tool(name, arguments=sanitized_args)

        # 3. Sanitize the response result
        # Pass original request arguments for context if needed by plugins
        sanitized_result = await sanitize_tool_call_result(
            plugin_manager=plugin_manager,
            server_name=self.name,
            tool_name=name,
            result=result,
            request_arguments=arguments,  # Pass original args for context
            mcp_context=mcp_context,  # Pass gateway context
        )

        return sanitized_result

    async def get_capabilities(self) -> Optional[types.ServerCapabilities]:
        """Gets the capabilities of the proxied server from the stored InitializeResult."""
        if self._server_info is None:
            logger.warning(
                f"Server '{self.name}' InitializeResult not available (initialization failed or pending?)."
            )
            return None
        if self._server_info.capabilities is None:
            # MCP spec says capabilities is required, but handle gracefully
            logger.warning(
                f"Server '{self.name}' did not report capabilities in InitializeResult."
            )
            return None
        # No sanitization typically needed for capabilities object itself
        # Plugins *could* be added here if needed (e.g., filtering reported capabilities)
        return self._server_info.capabilities


@dataclass
class GetewayContext:
    """Context holding the managed proxied servers and plugin manager."""

    proxied_servers: Dict[str, Server] = field(default_factory=dict)
    plugin_manager: Optional[PluginManager] = None
    mcp_json_path: Optional[str] = None


def main():
    """Entry point for backward compatibility - delegates to gateway.main()"""
    # Import here to avoid circular imports
    from mcp_gateway.gateway import main as gateway_main

    logger.info("Starting MCP Gateway server via legacy server.py entry point...")
    gateway_main()


if __name__ == "__main__":
    main()
