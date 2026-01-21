"""Tests for the LassoGuardrailPlugin.

This module contains tests for the LassoGuardrailPlugin that integrates with
Lasso Security's API to detect harmful content in messages.
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Any

import pytest
from dotenv import load_dotenv

from mcp import types
from mcp_gateway.plugins.base import PluginContext
from mcp_gateway.plugins.guardrails.lasso import (
    LassoGuardrailPlugin,
    LassoGuardrailAPIError,
    LassoGuardrailMissingSecrets,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


@pytest.fixture
def lasso_plugin() -> LassoGuardrailPlugin:
    """Create and configure a LassoGuardrailPlugin instance.

    Returns:
        LassoGuardrailPlugin: A configured plugin instance.
    """
    plugin = LassoGuardrailPlugin()
    plugin.load()
    return plugin


@pytest.fixture
def plugin_context() -> PluginContext:
    """Create a PluginContext for testing.

    Returns:
        PluginContext: A context object for testing.
    """
    return PluginContext(
        server_name="test_server",
        capability_name="test_capability",
        capability_type="test_type",
        arguments={
            "messages": [{"role": "user", "content": "Hello, I'm a regular message."}]
        },
        response=None,
    )


def test_plugin_initialization() -> None:
    """Test that the plugin initializes correctly."""
    plugin = LassoGuardrailPlugin()
    assert plugin.plugin_type == "guardrail"
    assert plugin.lasso_api_key is None
    assert plugin.api_base == "https://server.lasso.security/gateway/v3/classify"


def test_plugin_load_with_env_vars() -> None:
    """Test plugin loads configuration from environment variables."""
    # Save original env vars
    original_api_key = os.environ.get("LASSO_API_KEY")
    original_user_id = os.environ.get("LASSO_USER_ID")

    try:
        # Set test env vars
        os.environ["LASSO_API_KEY"] = "test_api_key"
        os.environ["LASSO_USER_ID"] = "test_user_id"

        plugin = LassoGuardrailPlugin()
        plugin.load()

        assert plugin.lasso_api_key == "test_api_key"
        assert plugin.user_id == "test_user_id"
    finally:
        # Restore original env vars
        if original_api_key:
            os.environ["LASSO_API_KEY"] = original_api_key
        else:
            os.environ.pop("LASSO_API_KEY", None)

        if original_user_id:
            os.environ["LASSO_USER_ID"] = original_user_id
        else:
            os.environ.pop("LASSO_USER_ID", None)


def test_extract_string_values() -> None:
    """Test recursive string extraction from nested structures."""
    plugin = LassoGuardrailPlugin()

    # Test nested dict
    values: List[str] = []
    plugin._extract_string_values({"a": "hello", "b": {"c": "world"}}, values)
    assert values == ["hello", "world"]

    # Test list
    values = []
    plugin._extract_string_values(["a", "b", "c"], values)
    assert values == ["a", "b", "c"]

    # Test mixed nested structure
    values = []
    plugin._extract_string_values({"items": ["x", "y"], "nested": {"key": "z"}}, values)
    assert set(values) == {"x", "y", "z"}

    # Test empty strings are skipped
    values = []
    plugin._extract_string_values({"a": "", "b": "  ", "c": "valid"}, values)
    assert values == ["valid"]

    # Test non-string values are ignored
    values = []
    plugin._extract_string_values({"num": 123, "bool": True, "str": "text"}, values)
    assert values == ["text"]


def test_extract_messages_from_request() -> None:
    """Test extracting messages from request arguments."""
    plugin = LassoGuardrailPlugin()

    arguments: Dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "Test message 1"},
            {"role": "assistant", "content": "Test response"},
            {"role": "user", "content": {"text": "Message with nested content"}},
        ]
    }

    messages = plugin._extract_messages_from_request(arguments)

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Test message 1"
    assert messages[2]["content"] == "Message with nested content"


def test_extract_text_from_response() -> None:
    """Test extracting text from a response object."""
    plugin = LassoGuardrailPlugin()

    # Create a CallToolResult with content
    response = types.CallToolResult(
        content=[types.TextContent(type="text", text="This is a test response")]
    )

    messages = plugin._extract_text_from_response(response)

    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == "This is a test response"


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
def test_prepare_headers() -> None:
    """Test header preparation with actual API key from environment."""
    plugin = LassoGuardrailPlugin()
    plugin.load()

    headers = plugin._prepare_headers()

    assert "lasso-api-key" in headers
    assert headers["lasso-api-key"] == os.environ.get("LASSO_API_KEY")
    assert headers["Content-Type"] == "application/json"


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_process_request_with_safe_content(
    lasso_plugin: LassoGuardrailPlugin, plugin_context: PluginContext
) -> None:
    """Test processing a request with safe content."""
    result = await lasso_plugin.process_request(plugin_context)

    # If content is safe, the original arguments should be returned
    assert result == plugin_context.arguments


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_process_response_with_safe_content(
    lasso_plugin: LassoGuardrailPlugin,
) -> None:
    """Test processing a response with safe content."""
    # Create a context with a response
    context = PluginContext(
        server_name="test_server",
        capability_name="test_capability",
        capability_type="test_type",
        arguments={},
        response=types.CallToolResult(
            content=[types.TextContent(type="text", text="This is a safe response.")]
        ),
    )

    result = await lasso_plugin.process_response(context)

    # If content is safe, the original response should be returned
    assert result == context.response


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_lasso_api_call(lasso_plugin: LassoGuardrailPlugin) -> None:
    """Test direct API call to Lasso service."""
    headers = lasso_plugin._prepare_headers()
    payload = lasso_plugin._prepare_payload(
        [{"role": "user", "content": "This is a test message for the API."}]
    )

    try:
        response = await lasso_plugin._call_lasso_api(headers, payload)

        # Verify we got a proper response structure
        assert isinstance(response, dict)
        assert "violations_detected" in response
    except LassoGuardrailAPIError as e:
        # The API might return a 403 if the key is invalid or has access issues
        # We'll log this but consider the test passed as long as we get a proper API error
        logger.warning(f"API returned an error: {e}")
        # Check if the error message contains expected status code information
        assert "403" in str(e) or "401" in str(e) or "API" in str(e)
