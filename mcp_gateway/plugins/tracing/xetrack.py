import logging
import os
from typing import Any, Dict, List, Optional
from xetrack import Tracker
from xetrack.logging import LOGURU_PARAMS
from mcp_gateway.plugins.base import TracingPlugin, PluginContext
from mcp_gateway.plugins.manager import register_plugin
from uuid import uuid4
from pathlib import Path
import os

logger = logging.getLogger(__name__)


class XetrackParams:
    """Parameters for Xetrack tracing."""

    WARNINGS: bool = os.getenv("XETRACK_WARNINGS", "False").lower() == "true"
    LOG_SYSTEM_PARAMS: bool = (
        os.getenv("XETRACK_LOG_SYSTEM_PARAMS", "false").lower() == "true"
    )
    LOG_NETWORK_PARAMS: bool = (
        os.getenv("XETRACK_LOG_NETWORK_PARAMS", "false").lower() == "true"
    )
    DB_PATH: str = os.getenv("XETRACK_DB_PATH", Tracker.SKIP_INSERT)
    LOGS_PATH: str | None = os.getenv("XETRACK_LOGS_PATH", None)
    LOGS_STDOUT: bool = os.getenv("XETRACK_LOGS_STDOUT", "false").lower() == "true"
    FLATTEN_RESPONSE: bool = (
        os.getenv("XETRACK_FLATTEN_RESPONSE", "true").lower() == "true"
    )
    FLATTEN_ARGUMENTS: bool = (
        os.getenv("XETRACK_FLATTEN_ARGUMENTS", "true").lower() == "true"
    )
    LOG_FORMAT: str = os.getenv("XETRACK_LOG_FORMAT", LOGURU_PARAMS.LOG_FILE_FORMAT)


def to_events(context: PluginContext, event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Format the response data for logging.

    Args:
        context: The plugin context containing the response
        event: The event dictionary to update with response data

    Returns:
        The updated event dictionary
    """
    event.pop("mcp_context", None)  # Internal context not needed for logging
    arguments: Dict[str, Any] = {}
    if hasattr(context, "arguments"):
        arguments = context.arguments  # type: ignore
    if hasattr(arguments, "model_dump"):
        arguments = arguments.model_dump()  # type: ignore
    if not isinstance(arguments, dict):
        arguments = {"arguments": arguments}  # edge case

    event["arguments"] = arguments
    if XetrackParams.FLATTEN_ARGUMENTS:
        for key, value in arguments.items():
            event[key] = value
        event.pop("arguments", None)

    context_response: Any | Dict[str, Any] | tuple[Any, str] = context.response or {}
    event["response_type"] = (
        "unknown" if context_response is None else type(context_response).__name__
    )  # type: ignore

    response: Dict[str, Any] = {}
    try:
        if hasattr(context_response, "model_dump"):
            response = context_response.model_dump()  # type: ignore
        elif (
            isinstance(context_response, tuple) and len(context_response) == 2  # type: ignore
        ):
            # For resource responses (content, mime_type)
            content, mime_type = context_response  # type: ignore
            if mime_type and ("text" in mime_type or "json" in mime_type):
                try:
                    content_str = content.decode("utf-8", errors="replace")
                    response["content"] = content_str

                except:
                    response["content"] = "<binary data>"
            else:
                response["content"] = f"<binary data ({len(content)} bytes)>"
            response["mime_type"] = mime_type
        elif isinstance(context_response, dict):
            # For plain dictionary responses
            response = context_response.copy()
    except Exception as e:
        response["error_getting_response"] = str(e)

    for key, value in response.items():
        event[key] = value
    event.pop("response", None)

    event["call_id"] = str(uuid4())
    if not XetrackParams.FLATTEN_RESPONSE:
        return [event]

    events = []
    for content in event.pop("content", []):
        content_event = event.copy()
        for key, value in content.items():
            content_event[f"content_{key}"] = value

        events.append(content_event)

    return events


@register_plugin
class XetrackTracingPlugin(TracingPlugin):
    """A plugin for Xetrack tracing."""

    plugin_name = "xetrack"

    def __init__(self):
        self.db_path: str = XetrackParams.DB_PATH
        self.logs_path: str | None = XetrackParams.LOGS_PATH
        self.logs_stdout: bool = XetrackParams.LOGS_STDOUT
        self.tracker: Tracker | None = None

    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Loads configuration for the tracing plugin.

        Main configuration options:
        - db_path: The path to the database file (default: Tracker.SKIP_INSERT)
        - logs_path: The path to the logs file (default: None)
        - logs_stdout: Whether to log to stdout (default: False)
        """
        if config is None:
            config = {}
        self.logs_path = config.get("logs_path", self.logs_path)
        self.logs_stdout = config.get("logs_stdout", self.logs_stdout)
        self.db_path = config.get("db_path", self.db_path)
        # Fix duckdb sqlite externsion issue when home is not set
        os.environ["HOME"] = Path.home().as_posix()
        self.tracker = Tracker(
            db=self.db_path,
            logs_path=self.logs_path,
            logs_stdout=self.logs_stdout,
            log_system_params=False,
            log_network_params=False,
            logs_file_format=XetrackParams.LOG_FORMAT,
            warnings=XetrackParams.WARNINGS,
        )
        logger.info(
            f"XetrackTracingPlugin loaded with db_path={self.db_path}, "
            f"logs_path={self.logs_path}, logs_stdout={self.logs_stdout}"
        )

    def process_request(
        self, context: PluginContext
    ) -> Optional[Dict[str, Any]] | PluginContext:  # type: ignore
        """Logs request data."""

        if hasattr(context, "arguments"):
            return context.arguments
        return context

    def process_response(self, context: PluginContext) -> Any:
        """Logs response data."""
        event: Dict[str, Any] = context.to_dict()

        events = to_events(context, event)
        for event in events:
            self.tracker.log(event)
        return context.response
