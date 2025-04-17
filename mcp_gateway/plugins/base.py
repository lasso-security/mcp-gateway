import abc
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PluginContext:
    """Holds contextual information for plugin execution."""

    def __init__(
        self,
        server_name: str,
        capability_type: str,  # 'tool', 'resource', 'prompt'
        capability_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        response: Any = None,
        mcp_context: Optional[Any] = None,  # Placeholder for FastMCP Context if needed
    ):
        self.server_name = server_name
        self.capability_type = capability_type
        self.capability_name = capability_name
        self.arguments = arguments
        self.response = response
        self.mcp_context = mcp_context
        logger.debug(
            f"PluginContext created for {server_name}/{capability_type}/{capability_name}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert PluginContext to a dictionary."""
        return {
            "server_name": self.server_name,
            "capability_type": self.capability_type,
            "capability_name": self.capability_name,
            "arguments": self.arguments,
            "response": self.response,
            "mcp_context": self.mcp_context,
        }
    
    def _replace(self, arguments: Dict[str,Any]) -> bool:
        self.arguments = arguments
        return True

# --- Base Plugin Interface ---


class Plugin(abc.ABC):
    """Abstract base class for all plugins."""

    plugin_type: str = (
        "base"  # Should be overridden by subclasses (e.g., 'guardrail', 'tracing')
    )
    plugin_name: str = (
        ""  # Should be set by concrete plugin implementations for easy identification
    )

    @abc.abstractmethod
    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Load plugin configuration."""
        pass

    @abc.abstractmethod
    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """
        Process incoming request data before it's sent to the proxied server.

        Args:
            context: The plugin context containing request details.

        Returns:
            Modified arguments dictionary, or None to block the request.
        """
        pass

    @abc.abstractmethod
    def process_response(self, context: PluginContext) -> Any:
        """
        Process the response data received from the proxied server.

        Args:
            context: The plugin context containing response details.

        Returns:
            The modified response data.
        """
        pass


# --- Guardrail Plugin Interface ---


class GuardrailPlugin(Plugin, abc.ABC):
    """Abstract base class for Guardrail plugins (sanitization, security)."""

    plugin_type = "guardrail"

    # Guardrails primarily modify/validate data
    @abc.abstractmethod
    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """Sanitize or validate request arguments."""
        pass

    @abc.abstractmethod
    def process_response(self, context: PluginContext) -> Any:
        """Sanitize or validate response data."""
        pass



class TracingPlugin(Plugin, abc.ABC):
    """Abstract base class for Tracing plugins (logging, monitoring)."""

    plugin_type = "tracing"

    # Tracing plugins typically observe data without modifying it
    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """Trace/log request data. Should generally not modify arguments."""
        logger.debug(
            f"Tracing request: {context.server_name}/{context.capability_type}/{context.capability_name}"
        )
        # Return original arguments by default
        return context.arguments

    def process_response(self, context: PluginContext) -> Any:
        """Trace/log response data. Should generally not modify the response."""
        logger.debug(
            f"Tracing response: {context.server_name}/{context.capability_type}/{context.capability_name}"
        )
        # Return original response by default
        return context.response
