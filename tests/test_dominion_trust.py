"""
Tests for the Dominion Observatory Trust Verification Plugin.
"""

import json
import time
from typing import Any, Dict, Optional
from unittest.mock import patch, MagicMock

import pytest

from mcp_gateway.plugins.guardrails.dominion import (
    DominionTrustPlugin,
    TrustScoreCache,
    DEFAULT_TRUST_THRESHOLD,
    DEFAULT_CACHE_TTL_SECONDS,
)
from mcp_gateway.plugins.base import PluginContext


class TestTrustScoreCache:
    """Tests for the TrustScoreCache class."""

    def test_cache_miss(self):
        cache = TrustScoreCache(ttl_seconds=300)
        assert cache.get("unknown-server") is None

    def test_cache_hit(self):
        cache = TrustScoreCache(ttl_seconds=300)
        data = {"trust_score": 85}
        cache.set("my-server", data)
        assert cache.get("my-server") == data

    def test_cache_expiry(self):
        cache = TrustScoreCache(ttl_seconds=1)
        data = {"trust_score": 85}
        cache.set("my-server", data)
        assert cache.get("my-server") == data

        # Simulate time passing by manipulating the timestamp
        cache._cache["my-server"]["timestamp"] = time.monotonic() - 2
        assert cache.get("my-server") is None

    def test_cache_clear(self):
        cache = TrustScoreCache(ttl_seconds=300)
        cache.set("server-a", {"trust_score": 90})
        cache.set("server-b", {"trust_score": 70})
        cache.clear()
        assert cache.get("server-a") is None
        assert cache.get("server-b") is None


class TestDominionTrustPlugin:
    """Tests for the DominionTrustPlugin class."""

    @pytest.fixture
    def plugin(self) -> DominionTrustPlugin:
        """Provide a configured DominionTrustPlugin instance."""
        p = DominionTrustPlugin()
        p.load({})
        return p

    @pytest.fixture
    def plugin_fail_open(self) -> DominionTrustPlugin:
        """Provide a DominionTrustPlugin with fail_open=True."""
        p = DominionTrustPlugin()
        p.load({"fail_open": True})
        return p

    @pytest.fixture
    def tool_context(self) -> PluginContext:
        """Provide a PluginContext for a tool call."""
        return PluginContext(
            server_name="test-mcp-server",
            capability_type="tool",
            capability_name="run_query",
            arguments={"query": "SELECT 1"},
        )

    @pytest.fixture
    def prompt_context(self) -> PluginContext:
        """Provide a PluginContext for a prompt call."""
        return PluginContext(
            server_name="test-mcp-server",
            capability_type="prompt",
            capability_name="summarize",
            arguments={"text": "hello"},
        )

    def test_plugin_name(self, plugin: DominionTrustPlugin):
        assert plugin.plugin_name == "dominion"
        assert plugin.plugin_type == "guardrail"

    def test_load_default_config(self, plugin: DominionTrustPlugin):
        assert plugin.trust_threshold == DEFAULT_TRUST_THRESHOLD
        assert plugin.fail_open is False

    def test_load_custom_config(self):
        p = DominionTrustPlugin()
        p.load({
            "trust_threshold": 75,
            "cache_ttl_seconds": 120,
            "fail_open": True,
            "api_base_url": "https://custom.example.com",
        })
        assert p.trust_threshold == 75
        assert p.fail_open is True
        assert p.api_base_url == "https://custom.example.com"

    def test_skip_non_tool_calls(
        self, plugin: DominionTrustPlugin, prompt_context: PluginContext
    ):
        """Non-tool capability types should be allowed without checking trust."""
        result = plugin.process_request(prompt_context)
        assert result == prompt_context.arguments

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_allow_trusted_server(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """Servers with scores at or above the threshold should be allowed."""
        mock_fetch.return_value = {"trust_score": 85}
        result = plugin.process_request(tool_context)
        assert result == tool_context.arguments
        mock_fetch.assert_called_once_with("test-mcp-server")

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_block_untrusted_server(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """Servers with scores below the threshold should be blocked."""
        mock_fetch.return_value = {"trust_score": 30}
        result = plugin.process_request(tool_context)
        assert result is None
        mock_fetch.assert_called_once_with("test-mcp-server")

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_block_at_threshold_boundary(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """A score exactly at the threshold should be allowed."""
        mock_fetch.return_value = {"trust_score": 60}
        result = plugin.process_request(tool_context)
        assert result == tool_context.arguments

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_block_just_below_threshold(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """A score just below the threshold should be blocked."""
        mock_fetch.return_value = {"trust_score": 59}
        result = plugin.process_request(tool_context)
        assert result is None

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_api_failure_fail_closed(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """When API fails and fail_open=False, block the request."""
        mock_fetch.return_value = None
        result = plugin.process_request(tool_context)
        assert result is None

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_api_failure_fail_open(
        self,
        mock_fetch: MagicMock,
        plugin_fail_open: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """When API fails and fail_open=True, allow the request."""
        mock_fetch.return_value = None
        result = plugin_fail_open.process_request(tool_context)
        assert result == tool_context.arguments

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_missing_trust_score_field(
        self,
        mock_fetch: MagicMock,
        plugin: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """If the API response lacks a trust_score field, block by default."""
        mock_fetch.return_value = {"status": "unknown"}
        result = plugin.process_request(tool_context)
        assert result is None

    @patch.object(DominionTrustPlugin, "_fetch_trust_score")
    def test_missing_trust_score_field_fail_open(
        self,
        mock_fetch: MagicMock,
        plugin_fail_open: DominionTrustPlugin,
        tool_context: PluginContext,
    ):
        """If API response lacks trust_score and fail_open=True, allow the request."""
        mock_fetch.return_value = {"status": "unknown"}
        result = plugin_fail_open.process_request(tool_context)
        assert result == tool_context.arguments

    def test_process_response_passthrough(
        self, plugin: DominionTrustPlugin, tool_context: PluginContext
    ):
        """process_response should pass through the response unmodified."""
        tool_context.response = {"result": "some data"}
        result = plugin.process_response(tool_context)
        assert result == {"result": "some data"}

    @patch("mcp_gateway.plugins.guardrails.dominion.urllib.request.urlopen")
    def test_fetch_trust_score_success(
        self,
        mock_urlopen: MagicMock,
        plugin: DominionTrustPlugin,
    ):
        """Test successful API call to Dominion Observatory."""
        response_data = {"trust_score": 92, "server_name": "test-server"}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = plugin._fetch_trust_score("test-server")
        assert result == response_data

    @patch("mcp_gateway.plugins.guardrails.dominion.urllib.request.urlopen")
    def test_fetch_trust_score_caches_result(
        self,
        mock_urlopen: MagicMock,
        plugin: DominionTrustPlugin,
    ):
        """Test that results are cached and subsequent calls don't hit the API."""
        response_data = {"trust_score": 85}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        # First call should hit the API
        result1 = plugin._fetch_trust_score("cached-server")
        assert result1 == response_data
        assert mock_urlopen.call_count == 1

        # Second call should return cached result
        result2 = plugin._fetch_trust_score("cached-server")
        assert result2 == response_data
        assert mock_urlopen.call_count == 1  # No additional API call

    @patch("mcp_gateway.plugins.guardrails.dominion.urllib.request.urlopen")
    def test_fetch_trust_score_http_error(
        self,
        mock_urlopen: MagicMock,
        plugin: DominionTrustPlugin,
    ):
        """Test handling of HTTP errors from the API."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=404, msg="Not Found", hdrs={}, fp=None
        )
        result = plugin._fetch_trust_score("unknown-server")
        assert result is None

    @patch("mcp_gateway.plugins.guardrails.dominion.urllib.request.urlopen")
    def test_fetch_trust_score_connection_error(
        self,
        mock_urlopen: MagicMock,
        plugin: DominionTrustPlugin,
    ):
        """Test handling of connection errors."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        result = plugin._fetch_trust_score("unreachable-server")
        assert result is None
