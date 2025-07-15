#!/usr/bin/env python3

"""Simple test script to verify NPM version handling without pytest."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_gateway.security_scanner.npm_collector import NPMCollector
from mcp_gateway.security_scanner.config import Keys


def test_parse_scoped_package_with_version():
    """Test parsing scoped packages with version tags."""
    collector = NPMCollector("@upstash/context7-mcp@latest")

    assert collector.package_name == "@upstash/context7-mcp"
    assert collector.version_tag == "latest"
    assert collector.original_package_name == "@upstash/context7-mcp@latest"
    print("✓ test_parse_scoped_package_with_version passed")


def test_parse_scoped_package_without_version():
    """Test parsing scoped packages without version tags."""
    collector = NPMCollector("@angular/core")

    assert collector.package_name == "@angular/core"
    assert collector.version_tag is None
    assert collector.original_package_name == "@angular/core"
    print("✓ test_parse_scoped_package_without_version passed")


def test_parse_regular_package_with_version():
    """Test parsing regular packages with version tags."""
    collector = NPMCollector("express@4.18.2")

    assert collector.package_name == "express"
    assert collector.version_tag == "4.18.2"
    assert collector.original_package_name == "express@4.18.2"
    print("✓ test_parse_regular_package_with_version passed")


def test_parse_regular_package_without_version():
    """Test parsing regular packages without version tags."""
    collector = NPMCollector("lodash")

    assert collector.package_name == "lodash"
    assert collector.version_tag is None
    assert collector.original_package_name == "lodash"
    print("✓ test_parse_regular_package_without_version passed")


def test_parse_scoped_package_with_numeric_version():
    """Test parsing scoped packages with numeric versions."""
    collector = NPMCollector("@angular/core@16.0.0")

    assert collector.package_name == "@angular/core"
    assert collector.version_tag == "16.0.0"
    assert collector.original_package_name == "@angular/core@16.0.0"
    print("✓ test_parse_scoped_package_with_numeric_version passed")


def test_parse_scoped_package_with_beta_version():
    """Test parsing scoped packages with beta versions."""
    collector = NPMCollector("@vue/cli@5.0.0-beta.1")

    assert collector.package_name == "@vue/cli"
    assert collector.version_tag == "5.0.0-beta.1"
    assert collector.original_package_name == "@vue/cli@5.0.0-beta.1"
    print("✓ test_parse_scoped_package_with_beta_version passed")


def test_get_all_data_includes_version_info():
    """Test that get_all_data includes version information."""
    collector = NPMCollector("@upstash/context7-mcp@latest")

    # Mock the raw data to simulate successful fetch
    collector._raw_data = {
        "name": "@upstash/context7-mcp",
        "description": "Test package",
        "versions": {"1.0.0": {}},
    }

    data = collector.get_all_data()

    assert Keys.PACKAGE_NAME in data
    assert Keys.ORIGINAL_PACKAGE_NAME in data
    assert Keys.VERSION_TAG in data

    assert data[Keys.PACKAGE_NAME] == "@upstash/context7-mcp"
    assert data[Keys.ORIGINAL_PACKAGE_NAME] == "@upstash/context7-mcp@latest"
    assert data[Keys.VERSION_TAG] == "latest"
    print("✓ test_get_all_data_includes_version_info passed")


def test_edge_case_multiple_at_symbols():
    """Test handling of edge cases with multiple @ symbols."""
    collector = NPMCollector("@scope/package@1.0.0@beta")

    # Should treat last @ as version separator
    assert collector.package_name == "@scope/package@1.0.0"
    assert collector.version_tag == "beta"
    print("✓ test_edge_case_multiple_at_symbols passed")


def test_whitespace_handling():
    """Test that whitespace is properly handled."""
    collector = NPMCollector("  @upstash/context7-mcp@latest  ")

    assert collector.package_name == "@upstash/context7-mcp"
    assert collector.version_tag == "latest"
    assert collector.original_package_name == "  @upstash/context7-mcp@latest  "
    print("✓ test_whitespace_handling passed")


def test_api_url_construction():
    """Test that API URLs are constructed with clean package names."""
    collector = NPMCollector("@upstash/context7-mcp@latest")

    # Test the URL construction logic
    expected_registry_url = "https://registry.npmjs.org/@upstash/context7-mcp"
    expected_downloads_url = (
        "https://api.npmjs.org/downloads/point/last-month/@upstash/context7-mcp"
    )

    # Simulate the URL construction from fetch_data method
    package_url = f"{collector._NPM_REGISTRY_URL}/{collector.package_name}"
    downloads_url = (
        f"{collector._NPM_DOWNLOADS_API_URL}/last-month/{collector.package_name}"
    )

    assert package_url == expected_registry_url
    assert downloads_url == expected_downloads_url
    print("✓ test_api_url_construction passed")


def run_all_tests():
    """Run all tests."""
    print("Running NPM version handling tests...")

    try:
        test_parse_scoped_package_with_version()
        test_parse_scoped_package_without_version()
        test_parse_regular_package_with_version()
        test_parse_regular_package_without_version()
        test_parse_scoped_package_with_numeric_version()
        test_parse_scoped_package_with_beta_version()
        test_get_all_data_includes_version_info()
        test_edge_case_multiple_at_symbols()
        test_whitespace_handling()
        test_api_url_construction()

        print("\n🎉 All tests passed!")
        return True
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
