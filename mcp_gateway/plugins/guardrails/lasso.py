import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from mcp import types
from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext
from mcp_gateway.plugins.manager import register_plugin

logger = logging.getLogger(__name__)


class LassoGuardrailAPIError(Exception):
    """Exception raised when the Lasso API call fails."""


class LassoGuardrailMissingSecrets(Exception):
    """Exception raised when required API credentials are missing."""


@register_plugin
class LassoGuardrailPlugin(GuardrailPlugin):
    """
    A guardrail plugin that integrates with Lasso Security's API to detect
    harmful content in messages before they're sent to LLM services.
    """

    plugin_name = "lasso"

    def __init__(self):
        self.lasso_api_key: Optional[str] = None
        self.user_id: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.api_base: str = "https://server.lasso.security/gateway/v3/classify"
        self.http_client: Optional[httpx.AsyncClient] = None

    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Loads Lasso configuration and sets up the client.

        Configuration options:
        - lasso_api_key: The API key for Lasso (falls back to LASSO_API_KEY env var)
        - user_id: Optional user ID to associate with requests (falls back to LASSO_USER_ID env var)
        - conversation_id: Optional conversation ID (falls back to LASSO_CONVERSATION_ID env var)
        - api_base: URL for the Lasso API (default: https://server.lasso.security/gateway/v3/classify)
        """
        if config is None:
            config = {}

        # Load configuration with fallbacks to environment variables
        self.lasso_api_key = config.get("lasso_api_key") or os.environ.get(
            "LASSO_API_KEY"
        )
        self.user_id = config.get("user_id") or os.environ.get("LASSO_USER_ID")
        self.conversation_id = config.get("conversation_id") or os.environ.get(
            "LASSO_CONVERSATION_ID"
        )
        self.api_base = config.get("api_base", self.api_base)

        # Check that API key is available
        if not self.lasso_api_key:
            logger.warning(
                "Lasso API key not provided. The plugin will be loaded but will not be functional. "
                "Set LASSO_API_KEY env var or provide lasso_api_key in config."
            )

        # Initialize HTTP client
        self.http_client = httpx.AsyncClient(timeout=10.0)

        logger.info(
            f"LassoGuardrailPlugin loaded. API base: {self.api_base}, "
            f"User ID configured: {self.user_id is not None}, "
            f"Conversation ID configured: {self.conversation_id is not None}"
        )

    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare headers for the Lasso API request."""
        if not self.lasso_api_key:
            msg = (
                "Couldn't get Lasso API key, either set the `LASSO_API_KEY` in the environment or "
                "pass it as a parameter to the guardrail in the config file"
            )
            raise LassoGuardrailMissingSecrets(msg)

        headers: Dict[str, str] = {
            "lasso-api-key": self.lasso_api_key,
            "Content-Type": "application/json",
        }

        # Add optional headers if provided
        if self.user_id:
            headers["lasso-user-id"] = self.user_id

        if self.conversation_id:
            headers["lasso-conversation-id"] = self.conversation_id

        return headers

    def _prepare_payload(
        self, messages: List[Dict[str, str]], message_type: str = "PROMPT"
    ) -> Dict[str, Any]:
        """Prepare the payload for the Lasso API v3 request."""
        return {"messages": messages, "messageType": message_type}

    async def _call_lasso_api(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call the Lasso API and return the response."""
        logger.debug(f"Sending request to Lasso API: {payload}")
        if not self.http_client:
            self.http_client = httpx.AsyncClient(timeout=10.0)

        try:
            response = await self.http_client.post(
                url=self.api_base,
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            res = response.json()
            logger.debug(f"Lasso API response: {res}")
            return res
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Lasso API HTTP error: {e.response.status_code} - {e.response.text}"
            )
            raise LassoGuardrailAPIError(
                f"Lasso API returned error: {e.response.status_code}"
            )
        except httpx.RequestError as e:
            logger.error(f"Lasso API request error: {str(e)}")
            raise LassoGuardrailAPIError(f"Failed to connect to Lasso API: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error calling Lasso API: {str(e)}", exc_info=True)
            raise LassoGuardrailAPIError(f"Unexpected error: {str(e)}")

    def _process_lasso_response(self, response: Dict[str, Any]) -> None:
        """Process the Lasso API response and raise exceptions if violations are detected."""
        if response and response.get("violations_detected") is True:
            violated_deputies = self._parse_violated_deputies(response)
            logger.warning(f"Lasso guardrail detected violations: {violated_deputies}")
            error_message = (
                f"Guardrail violations detected: {', '.join(violated_deputies)}"
            )
            raise LassoGuardrailAPIError(error_message)

    def _parse_violated_deputies(self, response: Dict[str, Any]) -> List[str]:
        """Parse the response to extract violated deputies."""
        violated_deputies = []
        if "deputies" in response:
            for deputy, is_violated in response["deputies"].items():
                if is_violated:
                    violated_deputies.append(deputy)
        return violated_deputies

    def _extract_string_values(self, obj: Any, values: List[str]) -> None:
        """Recursively extract all string values from nested dicts/lists."""
        if isinstance(obj, str):
            if obj.strip():  # Skip empty strings
                values.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                self._extract_string_values(v, values)
        elif isinstance(obj, list):
            for item in obj:
                self._extract_string_values(item, values)

    def _extract_messages_from_request(
        self, arguments: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Extract messages from request arguments."""
        messages = []
        logger.debug(f"Extracting messages from request arguments: {arguments}")

        # Handle direct messages array in arguments (chat-style format)
        if (
            arguments
            and "messages" in arguments
            and isinstance(arguments["messages"], list)
        ):
            raw_messages = arguments["messages"]
            for msg in raw_messages:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    content = msg["content"]
                    if isinstance(content, dict) and "text" in content:
                        content = content["text"]
                    if isinstance(content, str):
                        messages.append({"role": msg["role"], "content": content})

        # If no messages format, extract string values per argument key
        # This handles MCP tools like falcon-mcp that use filter/query args
        if not messages and arguments:
            arg_contents: List[str] = []
            for key, value in arguments.items():
                key_strings: List[str] = []
                self._extract_string_values(value, key_strings)
                if key_strings:
                    arg_contents.append(f"{key}: {' '.join(key_strings)}")
            if arg_contents:
                combined_content = "; ".join(arg_contents)
                messages.append({"role": "user", "content": combined_content})
                logger.debug(
                    f"Extracted values from {len(arg_contents)} arguments for Lasso check"
                )

        if not messages:
            logger.warning("Could not extract messages from request arguments")

        return messages

    def _extract_text_from_response(self, response: Any) -> List[Dict[str, str]]:
        """Extract text content from response for Lasso API validation."""
        messages = []

        # Handle CallToolResult with content
        if (
            isinstance(response, types.CallToolResult)
            and hasattr(response, "content")
            and response.content
        ):
            for content_item in response.content:
                if isinstance(content_item, types.TextContent) and content_item.text:
                    messages.append({"role": "assistant", "content": content_item.text})

        # If we couldn't find text content in the expected format, log a warning
        if not messages:
            logger.debug(
                "Could not extract text content from response for Lasso validation"
            )

        return messages

    async def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """
        Process request arguments, checking message content against Lasso's API.
        Blocks the request by returning None if violations are found.
        """
        logger.debug(
            f"LassoGuardrail processing request for {context.server_name}/{context.capability_name}"
        )

        # Skip processing if no API key is configured
        if not self.lasso_api_key:
            logger.warning("Lasso API key not configured, skipping guardrail check")
            return context.arguments

        # Only process if arguments exist
        if not context.arguments:
            return context.arguments

        try:
            # Extract messages from the request arguments
            messages = self._extract_messages_from_request(context.arguments)

            # Skip if no messages to process
            if not messages:
                return context.arguments

            # Prepare and make API call
            headers = self._prepare_headers()
            payload = self._prepare_payload(messages)
            response = await self._call_lasso_api(headers, payload)

            # Process response
            try:
                self._process_lasso_response(response)
                # If no exceptions raised, request is safe
                return context.arguments
            except LassoGuardrailAPIError as e:
                # Create an error response for the blocked request
                logger.warning(f"Request blocked by Lasso guardrail: {str(e)}")
                # Return None to block the request
                return None

        except Exception as e:
            logger.error(
                f"Error in Lasso guardrail request processing: {str(e)}", exc_info=True
            )
            # On unexpected errors, let the request through (fail open)
            return context.arguments

    async def process_response(self, context: PluginContext) -> Any:
        """
        Process response data, checking content against Lasso's API.
        Blocks harmful content in responses.
        """
        logger.debug(
            f"LassoGuardrail processing response for {context.server_name}/{context.capability_name}"
        )

        # Skip processing if no API key is configured
        if not self.lasso_api_key:
            logger.warning("Lasso API key not configured, skipping guardrail check")
            return context.response

        # Only process if response exists
        if not context.response:
            return context.response

        try:
            # Extract text content from the response
            messages = self._extract_text_from_response(context.response)

            # Skip if no text content to process
            if not messages:
                return context.response

            # Prepare and make API call
            headers = self._prepare_headers()
            payload = self._prepare_payload(messages)
            response = await self._call_lasso_api(headers, payload)

            # Process response
            try:
                self._process_lasso_response(response)
                # If no exceptions raised, response is safe
                return context.response
            except LassoGuardrailAPIError as e:
                # Create an error response for the blocked content
                logger.warning(f"Response blocked by Lasso guardrail: {str(e)}")
                # Return error response with TextContent using 'text' type but error message
                return types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=f"[ERROR] Response blocked by security guardrail: {str(e)}",
                        )
                    ]
                )

        except Exception as e:
            logger.error(
                f"Error in Lasso guardrail response processing: {str(e)}", exc_info=True
            )
            # On unexpected errors, let the response through (fail open)
            return context.response
