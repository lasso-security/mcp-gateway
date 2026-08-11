import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp_gateway.plugins.base import LifecyclePlugin
from mcp_gateway.plugins.manager import register_plugin

logger = logging.getLogger(__name__)

DEFAULT_BASELINE_DIR = ".mcp-fingerprint"
FINGERPRINT_PYTHON_MIN = (3, 12)
FINGERPRINT_PYTHON_MAX = (3, 13)
_SAVE_REQUEST_SCHEMA = "mcp.fingerprint.save.request.v0.1"
_CHECK_REQUEST_SCHEMA = "mcp.fingerprint.check.request.v0.1"
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def fingerprint_supported() -> bool:
    """Return True when this Python runtime can use mcp-fingerprint."""
    version = sys.version_info[:2]
    return version >= FINGERPRINT_PYTHON_MIN and version < FINGERPRINT_PYTHON_MAX


def resolve_baseline_path(*, server_name: str, baseline_dir: str) -> str:
    """Resolve per-server baseline path under the configured directory."""
    cleaned = _SANITIZE_RE.sub("-", server_name.strip()).strip(".-_")
    if cleaned == "":
        cleaned = "server"
    return str(Path(baseline_dir) / f"{cleaned}.json")


@register_plugin
class McpFingerprintPlugin(LifecyclePlugin):
    """Observe-only MCP tool-contract fingerprinting at capability readiness.

    v1 has no runtime listChanged support; restart the gateway to re-check.
    """

    plugin_name = "mcp-fingerprint"

    def __init__(self) -> None:
        self._enabled = False
        self._baseline_dir = DEFAULT_BASELINE_DIR
        self._bootstrap = False
        self._project_live_snapshot = None
        self._save = None
        self._check = None

    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        if config is None:
            config = {}

        self._baseline_dir = config.get("baseline_dir", DEFAULT_BASELINE_DIR)
        self._bootstrap = bool(config.get("bootstrap", False))

        if not fingerprint_supported():
            logger.warning(
                "mcp-fingerprint plugin disabled: requires Python "
                f">={FINGERPRINT_PYTHON_MIN[0]}.{FINGERPRINT_PYTHON_MIN[1]} "
                f"and <{FINGERPRINT_PYTHON_MAX[0]}.{FINGERPRINT_PYTHON_MAX[1]}"
            )
            self._enabled = False
            return

        try:
            from mcp_fingerprint import check, project_live_snapshot, save
        except ImportError:
            logger.warning(
                "mcp-fingerprint plugin disabled: install with "
                "'pip install \"mcp-gateway[fingerprint]\"'"
            )
            self._enabled = False
            return

        self._project_live_snapshot = project_live_snapshot
        self._save = save
        self._check = check
        self._enabled = True
        mode = "bootstrap" if self._bootstrap else "observe"
        logger.info(
            "mcp-fingerprint plugin enabled (%s mode, baseline_dir=%s)",
            mode,
            self._baseline_dir,
        )

    def on_server_capabilities_ready(
        self, server_name: str, proxied_server: Any
    ) -> None:
        if not self._enabled:
            return

        try:
            snapshot = self._build_snapshot(proxied_server)
        except Exception as exc:
            self._log_observation_error(
                server_name,
                f"snapshot projection failed: {exc}",
            )
            return

        baseline_path = resolve_baseline_path(
            server_name=server_name,
            baseline_dir=self._baseline_dir,
        )

        if self._bootstrap:
            self._observe_bootstrap(server_name, snapshot, baseline_path)
        else:
            self._observe_check(server_name, snapshot, baseline_path)

    def _build_snapshot(self, proxied_server: Any) -> Dict[str, Any]:
        server_info = proxied_server._server_info
        if server_info is None or server_info.serverInfo is None:
            raise ValueError("server initialize result unavailable")

        server = {
            "name": server_info.serverInfo.name,
            "version": server_info.serverInfo.version,
        }
        tools = [tool.model_dump(mode="json") for tool in proxied_server._tools]
        return self._project_live_snapshot(server=server, tools=tools)

    def _observe_bootstrap(
        self, server_name: str, snapshot: Dict[str, Any], baseline_path: str
    ) -> None:
        result = self._save(
            {
                "schema_version": _SAVE_REQUEST_SCHEMA,
                "snapshot": snapshot,
                "baseline_path": baseline_path,
            }
        )
        if result.get("ok") is True:
            logger.info(
                "mcp-fingerprint [%s]: baseline created at %s (fingerprint=%s)",
                server_name,
                baseline_path,
                result.get("fingerprint"),
            )
            return

        failure = result.get("failure") or {}
        code = failure.get("code", "UNKNOWN")
        if code == "BASELINE_ALREADY_EXISTS":
            logger.info(
                "mcp-fingerprint [%s]: bootstrap skipped; baseline already exists at %s",
                server_name,
                baseline_path,
            )
            return

        self._log_observation_error(
            server_name,
            f"bootstrap failed ({code}): {failure.get('message', 'unknown error')}",
        )

    def _observe_check(
        self, server_name: str, snapshot: Dict[str, Any], baseline_path: str
    ) -> None:
        if not Path(baseline_path).is_file():
            self._log_observation_error(
                server_name,
                f"baseline missing at {baseline_path}",
                code="BASELINE_NOT_FOUND",
            )
            return

        result = self._check(
            {
                "schema_version": _CHECK_REQUEST_SCHEMA,
                "snapshot": snapshot,
                "baseline_path": baseline_path,
            }
        )
        if result.get("ok") is not True:
            failure = result.get("failure") or {}
            code = failure.get("code", "UNKNOWN")
            self._log_observation_error(
                server_name,
                f"check failed ({code}): {failure.get('message', 'unknown error')}",
                code=code,
            )
            return

        status = result.get("status")
        if status == "UNCHANGED":
            logger.info(
                "mcp-fingerprint [%s]: UNCHANGED (baseline=%s, fingerprint=%s)",
                server_name,
                baseline_path,
                result.get("fingerprint"),
            )
            return

        if status == "CHANGED":
            changes = result.get("changes") or []
            logger.warning(
                "mcp-fingerprint [%s]: CHANGED (baseline=%s, fingerprint=%s, changes=%s)",
                server_name,
                baseline_path,
                result.get("fingerprint"),
                changes,
            )
            return

        self._log_observation_error(
            server_name,
            f"unexpected check status: {status!r}",
        )

    def _log_observation_error(
        self, server_name: str, message: str, code: str = "OBSERVATION_ERROR"
    ) -> None:
        logger.error(
            "mcp-fingerprint [%s]: observation error (%s): %s",
            server_name,
            code,
            message,
        )
