"""
Dominion Observatory Trust Verification Plugin for MCP Gateway.

This guardrail plugin checks the behavioral trust score of MCP servers
via the Dominion Observatory API before allowing tool calls to proceed.
Servers with trust scores below a configurable threshold (default: 60)
are blocked from executing tool calls.

API Reference: https://dominion-observatory.sgdata.workers.dev
"""

import logging
import time
from typing import Any, Dict, Optional

import urllib.request
import json

from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext
from mcp_gateway.plugins.manager import register_plugin

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_API_BASE_URL = "https://dominion-observatory.sgdata.workers.dev"
DEFAULT_TRUST_THRESHOLD = 60
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5


class TrustScoreCache:
    """Simple in-memory cache for trust scores with TTL-based expiration."""

    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def get(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get a cached trust score if it exists and hasn't expired."""
        entry = self._cache.get(server_name)
        if entry is None:
            return None

        if time.monotonic() - entry["timestamp"] > self._ttl:
            del self._cache[server_name]
            logger.debug(f"Cache expired for server: {server_name}")
            return None

        logger.debug(f"Cache hit for server: {server_name}")
        return entry["data"]

    def set(self, server_name: str, data: Dict[str, Any]) -> None:
        """Cache a trust score result."""
        self._cache[server_name] = {
            "data": data,
            "timestamp": time.monotonic(),
        }
        logger.debug(f"Cached trust score for server: {server_name}")

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


@register_plugin
class DominionTrustPlugin(GuardrailPlugin):
    """
    Guardrail plugin that verifies MCP server trust scores via Dominion Observatory.

    Before any tool call is forwarded to a proxied MCP server, this plugin
    queries the Dominion Observatory API for the server's behavioral trust score.
    If the score is below the configured threshold, the request is blocked.

    Configuration options (passed via load()):
        - api_base_url: Base URL for the Dominion Observatory API
          (default: https://dominion-observatory.sgdata.workers.dev)
        - trust_threshold: Minimum trust score required (0-100, default: 60)
        - cache_ttl_seconds: How long to cache scores (default: 300 = 5 minutes)
        - request_timeout_seconds: HTTP request timeout (default: 5)
        - fail_open: If True, allow requests when the API is unreachable (default: False)
    """

    plugin_name = "dominion"
    plugin_type = "guardrail"

    def __init__(self):
        self.api_base_url: str = DEFAULT_API_BASE_URL
        self.trust_threshold: int = DEFAULT_TRUST_THRESHOLD
        self.request_timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS
        self.fail_open: bool = False
        self._cache: TrustScoreCache = TrustScoreCache()

    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Load plugin configuration."""
        if config is None:
            config = {}

        self.api_base_url = config.get("api_base_url", DEFAULT_API_BASE_URL)
        self.trust_threshold = config.get("trust_threshold", DEFAULT_TRUST_THRESHOLD)
        self.request_timeout = config.get(
            "request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS
        )
        self.fail_open = config.get("fail_open", False)

        cache_ttl = config.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS)
        self._cache = TrustScoreCache(ttl_seconds=cache_ttl)

        logger.info(
            f"DominionTrustPlugin loaded. "
            f"API: {self.api_base_url}, "
            f"threshold: {self.trust_threshold}, "
            f"cache TTL: {cache_ttl}s, "
            f"fail_open: {self.fail_open}"
        )

    def _fetch_trust_score(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the trust score for a server from the Dominion Observatory API.

        Returns the API response dict on success, or None on failure.
        """
        # Check cache first
        cached = self._cache.get(server_name)
        if cached is not None:
            return cached

        url = f"{self.api_base_url.rstrip('/')}/benchmark/{server_name}"
        logger.debug(f"Fetching trust score from: {url}")

        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "mcp-gateway-dominion-plugin/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # Cache the result
            self._cache.set(server_name, data)
            return data

        except urllib.error.HTTPError as e:
            logger.warning(
                f"Dominion Observatory API returned HTTP {e.code} for server '{server_name}': {e.reason}"
            )
            return None
        except urllib.error.URLError as e:
            logger.error(
                f"Failed to reach Dominion Observatory API for server '{server_name}': {e.reason}"
            )
            return None
        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON response from Dominion Observatory for server '{server_name}': {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error fetching trust score for server '{server_name}': {e}",
                exc_info=True,
            )
            return None

    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """
        Check the trust score of the target MCP server before allowing the request.

        Returns the original arguments if the server is trusted, or None to block
        the request if the server's trust score is below the threshold.
        """
        server_name = context.server_name

        # Only check trust for tool calls (the primary risk vector)
        if context.capability_type != "tool":
            logger.debug(
                f"Skipping trust check for non-tool capability: "
                f"{context.capability_type}/{context.capability_name}"
            )
            return context.arguments

        logger.info(
            f"Checking Dominion Observatory trust score for server '{server_name}' "
            f"(tool: {context.capability_name})"
        )

        result = self._fetch_trust_score(server_name)

        if result is None:
            if self.fail_open:
                logger.warning(
                    f"Trust score unavailable for server '{server_name}', "
                    f"allowing request (fail_open=True)"
                )
                return context.arguments
            else:
                logger.warning(
                    f"Trust score unavailable for server '{server_name}', "
                    f"blocking request (fail_open=False)"
                )
                return None

        trust_score = result.get("trust_score")
        if trust_score is None:
            logger.warning(
                f"No trust_score field in API response for server '{server_name}': {result}"
            )
            if self.fail_open:
                return context.arguments
            return None

        if trust_score < self.trust_threshold:
            logger.warning(
                f"BLOCKED: Server '{server_name}' has trust score {trust_score} "
                f"(threshold: {self.trust_threshold}). "
                f"Tool call '{context.capability_name}' denied."
            )
            return None

        logger.info(
            f"ALLOWED: Server '{server_name}' has trust score {trust_score} "
            f"(threshold: {self.trust_threshold}). "
            f"Tool call '{context.capability_name}' permitted."
        )
        return context.arguments

    def process_response(self, context: PluginContext) -> Any:
        """
        Pass through responses without modification.

        Trust verification is a pre-request check only; responses from
        trusted servers are returned as-is.
        """
        return context.response
