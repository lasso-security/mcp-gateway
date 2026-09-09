"""Regression tests for response-sanitization fail-closed behavior (#16)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest
from mcp import types

from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext
from mcp_gateway.plugins.manager import PluginManager
from mcp_gateway.sanitizers import sanitize_tool_call_result


SECRET = "super-secret-token-should-not-leak"


def _tool_result(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=False,
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

        raise SanitizationError("blocked by policy")


class _RaiseGenericPlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        raise RuntimeError("plugin crashed")


class _RedactingPlugin(_BaseGuardrail):
    def process_response(self, context: PluginContext) -> Any:
        return _tool_result("[REDACTED]")


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
    assert result.is_error is True
    joined = " ".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    assert SECRET not in joined
    assert "policy violation" in joined.lower() or "unexpected type" in joined.lower()


@pytest.mark.asyncio
async def test_sanitization_error_plugin_does_not_forward_upstream_secret() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RaiseSanitizationPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert result.is_error is True
    joined = " ".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    assert SECRET not in joined
    assert "blocked by policy" in joined


@pytest.mark.asyncio
async def test_generic_plugin_exception_does_not_forward_upstream_secret() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RaiseGenericPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert result.is_error is True
    joined = " ".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    assert SECRET not in joined


@pytest.mark.asyncio
async def test_healthy_plugin_still_returns_sanitized_result() -> None:
    upstream = _tool_result(SECRET)
    result = await sanitize_tool_call_result(
        plugin_manager=_manager_with(_RedactingPlugin()),
        server_name="demo",
        tool_name="echo",
        result=upstream,
    )
    assert result.is_error is False
    joined = " ".join(
        c.text for c in result.content if isinstance(c, types.TextContent)
    )
    assert joined == "[REDACTED]"
    assert SECRET not in joined


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
