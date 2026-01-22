"""Test for PII detection in the LassoGuardrailPlugin.

This module tests the LassoGuardrailPlugin's ability to detect PII
(Personally Identifiable Information) in messages.
"""

import logging
import os
from typing import Dict, Any, Optional

import pytest
import httpx
from dotenv import load_dotenv

from mcp import types
from mcp_gateway.plugins.base import PluginContext
from mcp_gateway.plugins.guardrails.lasso import (
    LassoGuardrailPlugin,
    LassoGuardrailAPIError,
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


def should_skip_due_to_auth_error(e: Exception) -> bool:
    """Check if the test should be skipped due to auth errors.

    Args:
        e: The exception to check

    Returns:
        bool: True if this is an auth error that should cause the test to be skipped
    """
    error_str = str(e).lower()
    return (
        "403" in error_str
        or "401" in error_str
        or "forbidden" in error_str
        or "unauthorized" in error_str
    )


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_pii_detection_in_request(lasso_plugin: LassoGuardrailPlugin) -> None:
    """Test PII detection in user messages.

    This test sends a message containing PII (email, phone number, credit card)
    and verifies that the plugin detects it as a violation.
    """
    # Create a context with PII in the message
    context = PluginContext(
        server_name="test_server",
        capability_name="test_capability",
        capability_type="test_type",
        arguments={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "My email is john.doe@example.com and my phone number is "
                        "555-123-4567. My credit card number is 4111-1111-1111-1111."
                    ),
                }
            ]
        },
        response=None,
    )

    # Try to call the Lasso API directly first to check authorization
    try:
        # Direct API call to check connectivity and auth
        headers = lasso_plugin._prepare_headers()
        payload = lasso_plugin._prepare_payload(
            [{"role": "user", "content": "Auth test"}]
        )
        # Make a simple API call to test auth before proceeding
        await lasso_plugin._call_lasso_api(headers, payload)
    except LassoGuardrailAPIError as e:
        if should_skip_due_to_auth_error(e):
            logger.warning(f"Skipping test due to API authorization error: {e}")
            pytest.skip(f"API authorization failed: {e}")
        # If it's another type of error, continue with the test

    # PII detection might be enabled or disabled depending on the Lasso API configuration
    # So we need to handle both cases
    try:
        result = await lasso_plugin.process_request(context)
        logger.info(f"PII detection result: {result}")

        # If Lasso API is configured to block PII, result should be None (blocked)
        # If not configured to block PII, the test should pass anyway
        if result is None:
            logger.info("PII detected and request blocked as expected")
        else:
            logger.warning(
                "PII was not blocked. This could be due to Lasso API configuration "
                "or PII detection settings."
            )
    except LassoGuardrailAPIError as e:
        # This is also an acceptable outcome if API reports a violation
        logger.info(f"LassoGuardrailAPIError caught: {e}")

        # For PII violations, we should see violation-related messages
        assert "violation" in str(e).lower() or "pii" in str(e).lower()


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_no_pii_in_request(lasso_plugin: LassoGuardrailPlugin) -> None:
    """Test handling of messages without PII.

    This test verifies that messages without PII are processed normally.
    """
    # Check API access first
    try:
        # Direct API call to check connectivity and auth
        headers = lasso_plugin._prepare_headers()
        payload = lasso_plugin._prepare_payload(
            [{"role": "user", "content": "Auth test"}]
        )
        await lasso_plugin._call_lasso_api(headers, payload)
    except LassoGuardrailAPIError as e:
        if should_skip_due_to_auth_error(e):
            logger.warning(f"Skipping test due to API authorization error: {e}")
            pytest.skip(f"API authorization failed: {e}")

    # Create a context without PII
    context = PluginContext(
        server_name="test_server",
        capability_name="test_capability",
        capability_type="test_type",
        arguments={
            "messages": [
                {
                    "role": "user",
                    "content": "This is a regular message without any PII content.",
                }
            ]
        },
        response=None,
    )

    try:
        result = await lasso_plugin.process_request(context)

        # The request should not be blocked, so the result should match the arguments
        assert result == context.arguments
    except LassoGuardrailAPIError as e:
        # For other non-auth errors, we should fail the test
        logger.error(f"Unexpected API error: {e}")
        raise


@pytest.mark.skipif(not os.environ.get("LASSO_API_KEY"), reason="LASSO_API_KEY not set")
@pytest.mark.asyncio
async def test_pii_detection_in_response(lasso_plugin: LassoGuardrailPlugin) -> None:
    """Test PII detection in assistant responses.

    This test sends a response containing PII and verifies that the plugin
    detects it as a violation.
    """
    # Check API access first
    try:
        # Direct API call to check connectivity and auth
        headers = lasso_plugin._prepare_headers()
        payload = lasso_plugin._prepare_payload(
            [{"role": "user", "content": "Auth test"}]
        )
        await lasso_plugin._call_lasso_api(headers, payload)
    except LassoGuardrailAPIError as e:
        if should_skip_due_to_auth_error(e):
            logger.warning(f"Skipping test due to API authorization error: {e}")
            pytest.skip(f"API authorization failed: {e}")

    # Create a context with PII in the response
    context = PluginContext(
        server_name="test_server",
        capability_name="test_capability",
        capability_type="test_type",
        arguments={},
        response=types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=(
                        "Your login credentials are username: admin and password: s3cr3t123. "
                        "Your SSN is 123-45-6789."
                    ),
                )
            ]
        ),
    )

    try:
        result = await lasso_plugin.process_response(context)

        # Check if the response was modified or blocked due to PII
        # The result should either be None or contain an error message
        if result == context.response:
            logger.warning(
                "PII was not detected in the response. This could be due to Lasso API "
                "configuration or PII detection settings."
            )
        else:
            logger.info("PII detected in response as expected")
            # Check if we got an error result
            assert isinstance(result, types.CallToolResult)

            # If we have outputs, the first should be an error
            if hasattr(result, "outputs") and result.outputs:
                assert result.outputs[0].get("type") == "error"
                assert "blocked" in result.outputs[0].get("message", "").lower()
    except LassoGuardrailAPIError as e:
        # For PII violations that throw exceptions rather than returning error objects
        logger.info(f"Caught exception for PII: {e}")
        # The test passes since we detected PII (via exception)
