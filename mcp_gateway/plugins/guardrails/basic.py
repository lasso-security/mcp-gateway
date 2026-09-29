import logging
import re
from typing import Any, Dict, Optional, List, Tuple

# Removed Presidio imports

from mcp import types
from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext

# Import SanitizationError if needed for response handling
# from mcp_gateway.sanitizers import SanitizationError
from mcp_gateway.plugins.manager import register_plugin

logger = logging.getLogger(__name__)

# Moved constants inside the class or initialized in __init__/load
TOKENS_REGEXES = {
    # --- Secrets ---
    "azure_ad_client_secret": {
        "regex": r'(?:^|[\\\'"`\s>=:(,)])([a-zA-Z0-9_~.]{3}\dQ~[a-zA-Z0-9_~.-]{31,34})(?:$|[\\\'"`\s<),])',
        "replacement": "<AZURE_KEY>",
    },
    "github_app_token": {
        "regex": r"(?:ghu|ghs)_[0-9a-zA-Z]{36}",
        "replacement": "<GITHUB_APP_TOKEN>",
    },
    "github_fine_grained_pat": {
        "regex": r"github_pat_\w{82}",
        "replacement": "<GITHUB_FINE_GRAINED_TOKEN>",
    },
    "github_oauth": {
        "regex": r"gho_[0-9a-zA-Z]{36}",
        "replacement": "<GITHUB_OAUTH_TOKEN>",
    },
    "github_pat": {
        "regex": r"ghp_[0-9a-zA-Z]{36}",
        "replacement": "<GITHUB_PERSONAL_ACCESS_TOKEN>",
    },
    "gcp_api_key": {
        "regex": r'\b(AIza[\w-]{35})(?:[`\'"\s;]|\\[nr]|$)',
        "replacement": "<GCP_API_KEY>",
    },
    "aws_access_token": {
        "regex": r"\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16})\b",
        "replacement": "<AWS_ACCESS_KEY>",
    },
    "jwt": {
        "regex": r'\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9\/\\_-]{17,}\.(?:[a-zA-Z0-9\/\\_-]{10,}={0,2})?)(?:[`\'"\s;]|\\[nr]|$)',
        "replacement": "<JWT_TOKEN>",
    },
    "gitlab_session_cookie": {
        "regex": r"_gitlab_session=[0-9a-z]{32}",
        "replacement": "<GITLAB_SESSION_TOKEN>",
    },
    "huggingface_access_token": {
        "regex": r'\b(hf_(?i:[a-z]{34}))(?:[`\'"\s;]|\\[nr]|$)',
        "replacement": "<HUGGINGFACE_TOKEN>",
    },
    "microsoft_teams_webhook": {
        "regex": r"https://[a-z0-9]+\.webhook\.office\.com/webhookb2/[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}@[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}/IncomingWebhook/[a-z0-9]{32}/[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}",
        "replacement": "<MICROSOFT_TEAMS_WEBHOOK>",
    },
    "slack_app_token": {
        "regex": r"(?i)xapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+",
        "replacement": "<SLACK_APP_TOKEN>",
    },
    "slack_bot_user_token": {
        # Bot (xoxb-), user (xoxp-), legacy workspace (xoxa-/xoxr-/xoxs-) and
        # configuration (xoxe-) tokens. The app-level token (xapp-) is handled
        # above; this covers the far more common xox[bparse]- family.
        "regex": r"(?i)\bxox[bparse]-[0-9a-z-]{10,}",
        "replacement": "<SLACK_BOT_TOKEN>",
    },
}

# Removed DEFAULT_PII_ENTITIES


@register_plugin
class BasicGuardrailPlugin(GuardrailPlugin):
    """
    A basic guardrail that removes common secrets using regex.
    """

    plugin_name = "basic"

    def __init__(self):
        # Removed Presidio-related attributes
        self.token_regexes: Dict[
            str, Dict[str, str]
        ] = {}  # Initialize empty, load populates
        self.compiled_regexes: Dict[str, re.Pattern] = {}  # Cache compiled regexes

    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Loads configuration for secret cleaning.
        Configuration options:
        - custom_token_regexes: Dict to add/override token regexes.
        """
        if config is None:
            config = {}

        # Start with default regexes and update with custom ones
        loaded_regexes = TOKENS_REGEXES.copy()
        custom_regexes = config.get("custom_token_regexes", {})
        loaded_regexes.update(custom_regexes)  # Merge custom regexes

        self.token_regexes = loaded_regexes
        self.compiled_regexes = {}  # Reset compiled regexes

        # Pre-compile regexes for efficiency and validation
        for token_type, pattern_data in self.token_regexes.items():
            try:
                self.compiled_regexes[token_type] = re.compile(pattern_data["regex"])
            except re.error as re_err:
                logger.warning(
                    f"Invalid regex for token type '{token_type}' during load: {pattern_data['regex']}. Error: {re_err}. Skipping this regex."
                )
                # Optionally remove the invalid regex from self.token_regexes
                # del self.token_regexes[token_type]

        logger.info(
            f"BasicGuardrailPlugin loaded. Secret patterns enabled: {len(self.compiled_regexes)}"
        )

    # Removed _pii_anonymizer method

    def _secret_cleaner(self, text: str) -> str:
        """Removes secrets from text using pre-compiled regex."""
        cleaned_text = text
        secrets_found = False
        try:
            for token_type, compiled_regex in self.compiled_regexes.items():
                replacement = self.token_regexes[token_type]["replacement"]
                # Use subn to check if replacements occurred
                cleaned_text, num_subs = compiled_regex.subn(replacement, cleaned_text)
                if num_subs > 0:
                    secrets_found = True
                    # Log first time a specific secret type is found in this text block
                    # logger.debug(f"Removed potential secret '{token_type}' from text.")

            if secrets_found:
                logger.info("Removed potential secrets from text using regex.")

        except Exception as e:
            logger.error(f"Error during secret cleaning: {e}", exc_info=True)
            return text  # Return original text on error
        return cleaned_text

    # Renamed _data_anonymizer to _sanitize_text for clarity
    def _sanitize_text(self, text: str) -> str:
        """Runs secret cleaning."""
        return self._secret_cleaner(text)

    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """
        Processes request arguments. Currently only logs.
        Can be extended to sanitize arguments if needed.
        """
        logger.debug(
            f"BasicGuardrail processing request for {context.server_name}/{context.capability_name}"
        )
        # Example: Sanitize a specific argument 'user_input'
        # if context.arguments and 'user_input' in context.arguments and isinstance(context.arguments['user_input'], str):
        #     original_text = context.arguments['user_input']
        #     sanitized_text = self._sanitize_text(original_text)
        #     if original_text != sanitized_text:
        #          logger.info(f"Sanitized secrets in request argument 'user_input' for {context.server_name}/{context.capability_name}")
        #          context.arguments['user_input'] = sanitized_text

        return context.arguments  # Return original/modified arguments

    def process_response(self, context: PluginContext) -> Any:
        """
        Processes response data, applying secret cleaning to text content.
        Currently targets mcp.types.CallToolResult, resource reads, and GetPromptResult.
        """
        logger.debug(
            f"BasicGuardrail processing response for {context.server_name}/{context.capability_name}"
        )
        response = context.response

        # --- Handle Tool Call Results ---
        if (
            isinstance(response, types.CallToolResult)
            and hasattr(response, "content")
            and response.content
        ):
            sanitized_content = []
            content_changed = False
            for content_item in response.content:
                if isinstance(content_item, types.TextContent):
                    original_text = content_item.text
                    sanitized_text = self._sanitize_text(original_text)
                    if original_text != sanitized_text:
                        content_changed = True
                    # Create a new TextContent to avoid modifying the original if it's shared
                    sanitized_content.append(
                        types.TextContent(type="text", text=sanitized_text)
                    )
                else:
                    # Keep non-text contents as they are
                    sanitized_content.append(content_item)

            # Return new object only if changes were made
            if content_changed:
                logger.info(
                    f"Cleaned secrets from CallToolResult content for {context.server_name}/{context.capability_name}"
                )
                # Create a new CallToolResult with the sanitized content
                return types.CallToolResult(
                    content=sanitized_content, isError=response.isError
                )
            else:
                return response  # Return original if no changes

        # --- Handle Resource Reads (Tuple[bytes, Optional[str]]) ---
        elif (
            isinstance(response, tuple)
            and len(response) == 2
            and isinstance(response[0], bytes)
        ):
            content_bytes, mime_type = response
            # Only attempt to sanitize if it's likely text
            if mime_type and (
                "text" in mime_type or "json" in mime_type or "xml" in mime_type
            ):
                try:
                    # Decode cautiously
                    original_text = content_bytes.decode("utf-8", errors="replace")
                    sanitized_text = self._sanitize_text(original_text)
                    if original_text != sanitized_text:
                        logger.info(
                            f"Cleaned secrets from text-based resource response for {context.server_name}/{context.capability_name}"
                        )
                        sanitized_bytes = sanitized_text.encode("utf-8")
                        return sanitized_bytes, mime_type
                    else:
                        return (
                            content_bytes,
                            mime_type,
                        )  # Return original bytes if no changes
                except Exception as e:
                    logger.error(
                        f"Error cleaning secrets from resource content: {e}",
                        exc_info=True,
                    )
                    return content_bytes, mime_type  # Return original on error
            else:
                # Not text, return original
                return content_bytes, mime_type

        # --- Handle GetPromptResult ---
        elif isinstance(response, types.GetPromptResult) and response.messages:
            sanitized_messages = []
            message_changed = False
            for message in response.messages:
                if isinstance(message.content, types.TextContent):
                    original_text = message.content.text
                    sanitized_text = self._sanitize_text(original_text)
                    if original_text != sanitized_text:
                        message_changed = True
                        # Create new content and message objects to avoid side effects
                        sanitized_content = types.TextContent(
                            type="text", text=sanitized_text
                        )
                        sanitized_message = types.Message(
                            role=message.role, content=sanitized_content
                        )
                        sanitized_messages.append(sanitized_message)
                    else:
                        # No change, keep original
                        sanitized_messages.append(message)
                else:
                    # Non-text content, keep as-is
                    sanitized_messages.append(message)

            if message_changed:
                logger.info(
                    f"Cleaned secrets from GetPromptResult messages for {context.server_name}/{context.capability_name}"
                )
                # Create a new GetPromptResult with sanitized messages
                return types.GetPromptResult(messages=sanitized_messages)
            else:
                return response  # Return original if no changes

        # --- Default case: return unmodified response ---
        return response
