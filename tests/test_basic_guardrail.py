import pytest
import os
import re
from typing import Dict, Any, Optional

from mcp_gateway.plugins.guardrails.basic import BasicGuardrailPlugin


class TestBasicGuardrailPlugin:
    """
    Test suite for BasicGuardrailPlugin focusing on anonymization functionality.
    """

    @pytest.fixture
    def pii_sample_text(self) -> str:
        """
        Fixture providing sample text with PII data from simple_pii_example.py.
        """
        with open(
            os.path.join(os.path.dirname(__file__), "simple_pii_example.py"), "r"
        ) as f:
            return f.read()

    @pytest.fixture
    def plugin(self) -> BasicGuardrailPlugin:
        """
        Fixture providing a configured BasicGuardrailPlugin instance.
        """
        plugin = BasicGuardrailPlugin()
        plugin.load()
        return plugin

    def test_secret_cleaner(
        self, plugin: BasicGuardrailPlugin, pii_sample_text: str
    ) -> None:
        """
        Test that _secret_cleaner correctly anonymizes secrets in the sample text.
        """
        cleaned_text = plugin._secret_cleaner(pii_sample_text)

        # The GitHub OAuth token should be anonymized
        assert "gho_16C7e42F292c6912E7710c838347Ae178B4a" not in cleaned_text
        assert "<GITHUB_OAUTH_TOKEN>" in cleaned_text

        # Original functional parts of the code should still be present
        assert "import requests" in cleaned_text
        assert "api_url = " in cleaned_text

    def test_sanitize_text(
        self, plugin: BasicGuardrailPlugin, pii_sample_text: str
    ) -> None:
        """
        Test that _sanitize_text correctly applies secret anonymization.
        Note: BasicGuardrailPlugin only handles secrets, not PII.
        """
        anonymized_text = plugin._sanitize_text(pii_sample_text)

        # GitHub OAuth token should be anonymized
        assert "gho_16C7e42F292c6912E7710c838347Ae178B4a" not in anonymized_text
        assert "<GITHUB_OAUTH_TOKEN>" in anonymized_text

        # If Presidio is loaded, PII might also be anonymized, but we don't assert this
        # as it depends on the environment
