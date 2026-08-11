"""Integration tests for observe-only mcp-fingerprint lifecycle plugin."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from mcp import types

from mcp_gateway.plugins.lifecycle.mcp_fingerprint import (
    DEFAULT_BASELINE_DIR,
    McpFingerprintPlugin,
    fingerprint_supported,
    resolve_baseline_path,
)
from mcp_gateway.plugins.manager import PluginManager
from mcp_gateway.server import Server

FIXTURE_SERVER = str(
    Path(__file__).resolve().parent / "fixtures" / "minimal_stdio_server.py"
)


def _write_gateway_config(path: Path, servers: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-gateway": {
                        "command": "mcp-gateway",
                        "args": [],
                        "servers": servers,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


class _StubServer:
    """Minimal stand-in for Server with initialize result and cached tools."""

    def __init__(
        self,
        *,
        name: str = "fixture-server",
        version: str = "0.1.0",
        tools: List[types.Tool] | None = None,
    ) -> None:
        self._server_info = types.InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=types.ServerCapabilities(tools={}),
            serverInfo=types.Implementation(name=name, version=version),
        )
        self._tools = tools or [
            types.Tool(
                name="echo",
                description="Echo the input message.",
                inputSchema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            )
        ]


def _fingerprint_extra_available() -> bool:
    """True when McpFingerprintPlugin.load() enables the optional extra."""
    probe = McpFingerprintPlugin()
    probe.load({})
    return probe._enabled


@pytest.fixture
def baseline_dir(tmp_path: Path) -> Path:
    return tmp_path / "baselines"


@pytest.fixture
def plugin(baseline_dir: Path) -> McpFingerprintPlugin:
    plugin = McpFingerprintPlugin()
    plugin.load(
        {
            "baseline_dir": str(baseline_dir),
            "bootstrap": False,
        }
    )
    if not plugin._enabled:
        pytest.skip("mcp-fingerprint optional extra not available")
    return plugin


@pytest.fixture
def bootstrap_plugin(baseline_dir: Path) -> McpFingerprintPlugin:
    plugin = McpFingerprintPlugin()
    plugin.load(
        {
            "baseline_dir": str(baseline_dir),
            "bootstrap": True,
        }
    )
    if not plugin._enabled:
        pytest.skip("mcp-fingerprint optional extra not available")
    return plugin


@pytest.fixture
def stub_server() -> _StubServer:
    return _StubServer()


def _baseline_path(baseline_dir: Path, server_name: str = "fixture-server") -> Path:
    return Path(resolve_baseline_path(server_name=server_name, baseline_dir=str(baseline_dir)))


def test_explicit_bootstrap_creates_baseline(
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)

    baseline_file = _baseline_path(baseline_dir, "fixture")
    assert baseline_file.is_file()
    payload = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mcp.fingerprint.baseline.v0.1"
    assert "baseline created" in caplog.text


def test_unchanged(
    plugin: McpFingerprintPlugin,
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)
    caplog.clear()

    with caplog.at_level(logging.INFO):
        plugin.on_server_capabilities_ready("fixture", stub_server)

    assert "UNCHANGED" in caplog.text


def test_changed(
    plugin: McpFingerprintPlugin,
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)
    changed_server = _StubServer(
        tools=[
            types.Tool(
                name="echo",
                description="Changed description.",
                inputSchema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            )
        ]
    )
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        plugin.on_server_capabilities_ready("fixture", changed_server)

    assert "CHANGED" in caplog.text


def test_deterministic_changed_output(
    plugin: McpFingerprintPlugin,
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
) -> None:
    bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)
    changed_server = _StubServer(
        tools=[
            types.Tool(
                name="echo",
                description="Changed description.",
                inputSchema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            )
        ]
    )

    from mcp_fingerprint import check

    snapshot = plugin._build_snapshot(changed_server)
    baseline_path = resolve_baseline_path(
        server_name="fixture", baseline_dir=str(baseline_dir)
    )
    first = check(
        {
            "schema_version": "mcp.fingerprint.check.request.v0.1",
            "snapshot": snapshot,
            "baseline_path": baseline_path,
        }
    )
    second = check(
        {
            "schema_version": "mcp.fingerprint.check.request.v0.1",
            "snapshot": snapshot,
            "baseline_path": baseline_path,
        }
    )
    assert first["status"] == "CHANGED"
    assert second["status"] == "CHANGED"
    assert first["changes"] == second["changes"]


def test_multiple_servers_independent_baselines(
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
) -> None:
    server_a = _StubServer(name="server-a", version="1.0.0")
    server_b = _StubServer(name="server-b", version="2.0.0")

    bootstrap_plugin.on_server_capabilities_ready("server-a", server_a)
    bootstrap_plugin.on_server_capabilities_ready("server-b", server_b)

    baseline_a = _baseline_path(baseline_dir, "server-a")
    baseline_b = _baseline_path(baseline_dir, "server-b")
    assert baseline_a.is_file()
    assert baseline_b.is_file()
    assert baseline_a != baseline_b


def test_icons_meta_execution_do_not_cause_false_drift(
    plugin: McpFingerprintPlugin,
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    baseline_tool = types.Tool(
        name="echo",
        description="Echo the input message.",
        inputSchema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    live_tool = types.Tool(
        name="echo",
        description="Echo the input message.",
        inputSchema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        icons=[{"src": "https://example.com/icon.png"}],
        _meta={"vendor": "fixture"},
        execution={"mode": "sync"},
    )
    bootstrap_plugin.on_server_capabilities_ready(
        "fixture", _StubServer(tools=[baseline_tool])
    )
    caplog.clear()

    with caplog.at_level(logging.INFO):
        plugin.on_server_capabilities_ready(
            "fixture", _StubServer(tools=[live_tool])
        )

    assert "]: UNCHANGED" in caplog.text
    assert "]: CHANGED" not in caplog.text


def test_invalid_baseline_observation_error_gateway_continues(
    plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    baseline_file = _baseline_path(baseline_dir, "fixture")
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_file.write_text("{not-valid-json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        plugin.on_server_capabilities_ready("fixture", stub_server)

    assert "observation error" in caplog.text
    assert "BASELINE_INVALID" in caplog.text


def test_missing_baseline_observe_mode_gateway_continues(
    plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        plugin.on_server_capabilities_ready("fixture", stub_server)

    assert "observation error" in caplog.text
    assert "BASELINE_NOT_FOUND" in caplog.text


def test_bootstrap_never_overwrites_existing_baseline(
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)
    baseline_file = _baseline_path(baseline_dir, "fixture")
    original = baseline_file.read_text(encoding="utf-8")
    caplog.clear()

    with caplog.at_level(logging.INFO):
        bootstrap_plugin.on_server_capabilities_ready("fixture", stub_server)

    assert baseline_file.read_text(encoding="utf-8") == original
    assert "bootstrap skipped" in caplog.text


def test_changed_never_blocks_gateway(
    plugin: McpFingerprintPlugin,
    bootstrap_plugin: McpFingerprintPlugin,
    baseline_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bootstrap_plugin.on_server_capabilities_ready(
        "fixture",
        _StubServer(
            tools=[
                types.Tool(
                    name="echo",
                    description="Original.",
                    inputSchema={"type": "object", "properties": {}},
                )
            ],
        ),
    )
    caplog.clear()

    plugin.on_server_capabilities_ready(
        "fixture",
        _StubServer(
            tools=[
                types.Tool(
                    name="echo",
                    description="Changed.",
                    inputSchema={"type": "object", "properties": {}},
                )
            ],
        ),
    )
    assert "CHANGED" in caplog.text


def test_plugin_exception_never_blocks_gateway(
    plugin: McpFingerprintPlugin,
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch.object(
        plugin, "_build_snapshot", side_effect=RuntimeError("boom")
    ), caplog.at_level(logging.ERROR):
        plugin.on_server_capabilities_ready("fixture", stub_server)

    assert "observation error" in caplog.text


@pytest.mark.asyncio
async def test_plugin_manager_isolates_lifecycle_exceptions(
    stub_server: _StubServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = PluginManager(
        enabled_types=["lifecycle"],
        enabled_plugins={"lifecycle": ["mcp-fingerprint"]},
        plugin_configs={"mcp-fingerprint": {"baseline_dir": "/tmp/unused"}},
    )
    plugin = manager.get_plugins("lifecycle")[0]

    with patch.object(
        plugin, "on_server_capabilities_ready", side_effect=RuntimeError("boom")
    ), caplog.at_level(logging.ERROR):
        await manager.notify_server_capabilities_ready("fixture", stub_server)

    assert "Error in lifecycle plugin" in caplog.text


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _fingerprint_extra_available(),
    reason="mcp-fingerprint optional extra not available",
)
async def test_tool_registration_unchanged_with_fingerprint_enabled(
    tmp_path: Path,
) -> None:
    mcp_json = tmp_path / "mcp.json"
    _write_gateway_config(
        mcp_json,
        {
            "fixture": {
                "command": sys.executable,
                "args": [FIXTURE_SERVER],
            }
        },
    )

    from mcp_gateway import gateway as gateway_module

    original_cli_args = gateway_module.cli_args
    gateway_module.cli_args = gateway_module.parse_args(
        [
            "--mcp-json-path",
            str(mcp_json),
            "-p",
            "mcp-fingerprint",
            "--fingerprint-baseline-dir",
            str(tmp_path / "fp"),
            "--fingerprint-bootstrap",
        ]
    )

    try:
        async with gateway_module.lifespan(gateway_module.mcp) as context:
            proxied = context.proxied_servers["fixture"]
            assert proxied.session is not None
            assert len(proxied._tools) >= 1
            tool_names = {tool.name for tool in proxied._tools}
            assert "echo" in tool_names
    finally:
        gateway_module.cli_args = original_cli_args


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _fingerprint_extra_available(),
    reason="mcp-fingerprint optional extra not available",
)
async def test_tool_calls_unchanged_with_fingerprint_enabled(
    tmp_path: Path,
) -> None:
    mcp_json = tmp_path / "mcp.json"
    _write_gateway_config(
        mcp_json,
        {
            "fixture": {
                "command": sys.executable,
                "args": [FIXTURE_SERVER],
            }
        },
    )

    from mcp_gateway import gateway as gateway_module

    original_cli_args = gateway_module.cli_args
    gateway_module.cli_args = gateway_module.parse_args(
        [
            "--mcp-json-path",
            str(mcp_json),
            "-p",
            "mcp-fingerprint",
            "--fingerprint-baseline-dir",
            str(tmp_path / "fp"),
            "--fingerprint-bootstrap",
        ]
    )

    try:
        async with gateway_module.lifespan(gateway_module.mcp) as context:
            proxied = context.proxied_servers["fixture"]
            result = await proxied.call_tool(
                plugin_manager=context.plugin_manager,
                name="echo",
                arguments={"message": "hello"},
            )
            assert result.isError is not True
            assert any(
                getattr(content, "text", "") == "hello"
                for content in (result.content or [])
            )
    finally:
        gateway_module.cli_args = original_cli_args


def test_optional_feature_absent_on_unsupported_python_does_not_break_core(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plugin = McpFingerprintPlugin()
    with patch(
        "mcp_gateway.plugins.lifecycle.mcp_fingerprint.fingerprint_supported",
        return_value=False,
    ), caplog.at_level(logging.WARNING):
        plugin.load({})

    assert plugin._enabled is False
    assert "disabled" in caplog.text

    stub = _StubServer()
    plugin.on_server_capabilities_ready("fixture", stub)


@pytest.mark.skipif(
    not fingerprint_supported(),
    reason="integration fixture requires Python 3.12.x",
)
@pytest.mark.asyncio
async def test_real_stdio_fixture_server_starts(tmp_path: Path) -> None:
    server = Server(
        "fixture",
        {"command": sys.executable, "args": [FIXTURE_SERVER]},
    )
    await server.start()
    try:
        assert server.session is not None
        assert any(tool.name == "echo" for tool in server._tools)
    finally:
        await server.stop()
