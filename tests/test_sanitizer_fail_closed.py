"""Regression tests for response-sanitization fail-closed behavior (#16)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest
from mcp import types

from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext
from mcp_gateway.plugins.manager import PluginManager
from mcp_gateway.sanitizers import sanitize_resource_read, sanitize_tool_call_result


SECRET = "super-secret-token-should-not-leak"


def _tool_result(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=False,
    )


def _is_error(result: types.CallToolResult) -> bool:
    """Version-safe error flag (mcp may expose is_error and/or isError)."""
    val = getattr(result, "is_error", None)
    if val is None:
        val = getattr(result, "isError", None)
    return bool(val)


def _joined_text(result: types.CallToolResult) -> str:
    return " ".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )


class _BaseGuardrail(GuardrailPlugin):
    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        return None

    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        return context.arguments

    def process_response(self, context: PluginContext) -> Any:
        return context.response


class _WrongTypePlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        return "not-a-call-tool-result"


class _RaiseSanitizationPlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        from mcp_gateway.sanitizers import SanitizationError

        raise SanitizationError(f"blocked by policy; payload={SECRET}")


class _RaiseGenericPlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        raise RuntimeError(f"plugin crashed; payload={SECRET}")


class _RedactingPlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        return _tool_result("[REDACTED]")


class _BadMimePlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        return (b"ok", {"not": "a-string"})


def _manager_with(plugin: GuardrailPlugin) -> PluginManager:
    manager = PluginManager.__new__(PluginManager)
    manager.enabled_types = {GuardrailPlugin.plugin_type}
    manager._plugins = {GuardrailPlugin.plugin_type: [plugin]}
    return manager


@pytest.mark.asyncio
async def test_wrong_type_plugin_does_not_forward_upstream_secret() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_WrongTypePlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert isinstance(result, types.CallToolResult)
    assert _is_error(result) is True
    joined = _joined_text(result)
    assert SECRET not in joined
    assert joined == "Gateway policy violation"


@pytest.mark.asyncio
async def test_sanitization_error_plugin_does_not_forward_upstream_secret() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RaiseSanitizationPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert _is_error(result) is True
    joined = _joined_text(result)
    assert SECRET not in joined
    assert joined == "Gateway policy violation"
    assert "blocked by policy" not in joined


@pytest.mark.asyncio
async def test_generic_plugin_exception_does_not_forward_upstream_secret() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RaiseGenericPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert _is_error(result) is True
    joined = _joined_text(result)
    assert SECRET not in joined
    assert joined == "Gateway policy violation"
    assert "plugin crashed" not in joined


@pytest.mark.asyncio
async def test_healthy_plugin_still_returns_sanitized_result() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RedactingPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert _is_error(result) is False
    joined = _joined_text(result)
    assert joined == "[REDACTED]"
    assert SECRET not in joined


@pytest.mark.asyncio
async def test_resource_bad_mime_type_is_blocked() -> None:
    from mcp_gateway.sanitizers import SanitizationError

    with pytest.raises(SanitizationError):
        await sanitize_resource_read(
            plugin_manager=_manager_with(_BadMimePlugin()),
            server_name="demo",
            uri="file:///secret",
            content=SECRET.encode(),
            mime_type="text/plain",
        )


@pytest.mark.asyncio
async def test_guardrail_request_exception_blocks_args() -> None:
    class BoomRequest(_BaseGuardrail):
        def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
            raise RuntimeError("request plugin crashed")

    manager = _manager_with(BoomRequest())
    blocked = await manager.process_request(
        PluginContext(
            server_name="demo",
            capability_type="tool",
            capability_name="echo",
            arguments={"path": "/etc/shadow"},
            mcp_context=MagicMock(),
        )
    )
    assert blocked is None
