import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple
from mcp import types

CONFIG_FILE_NAME = "mcp.json"

logger = logging.getLogger(__name__)
# Configure logging once, preferably at the application entry point
# logging.basicConfig(level=logging.INFO) # Removed basicConfig here


class Constants:
    SERVERS = "servers"
    
    
def find_config_file(mcp_json_path: str) -> Path | None:
    """Uses the provided mcp_json_path to locate the configuration file.

    Args:
        mcp_json_path: Path to the mcp.json configuration file.

    Returns:
        Path object pointing to the configuration file if it exists, None otherwise.
    """
    config_path = Path(mcp_json_path)
    try:
        resolved_path = config_path.resolve()
        if resolved_path.is_file():
            logger.warning(f"Found config file at: {resolved_path}")
            return resolved_path
        else:
            logger.warning(f"File not found at resolved path: {resolved_path}")
            return None
    except OSError as e:
        logger.warning(f"Error checking path {config_path}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error checking path {config_path}: {e}")
        return None


def load_servers_config_from_path(config_path: Path) -> Dict[str, Any]:
    """Loads the proxied server configurations from a specific config file path.

    Navigates the JSON structure: finds the top-level 'mcpServers', identifies
    the gateway's own configuration entry within it, and extracts the nested
    'servers' dictionary which contains the configurations for the servers
    being proxied.

    Args:
        config_path: The Path object pointing to the mcp.json file.

    Returns:
        A dictionary where keys are the names of the proxied servers and
        values are their configuration dictionaries. Returns an empty dictionary
        if the file is not found, invalid JSON, or the expected nested
        'servers' structure is missing or invalid.
    """
    logger.info(f"Loading configuration from: {config_path}")
    if not config_path.is_file():
        logger.error(f"Configuration file not found at specified path: {config_path}")
        return {}  # Return empty dict directly

    try:
        with open(config_path, "r") as f:
            full_config_data = json.load(f)

        # 1. Get the top-level 'mcpServers' dictionary
        top_level_mcp_servers = full_config_data.get("mcpServers")
        if not isinstance(top_level_mcp_servers, dict):
            logger.warning(
                f"Top-level 'mcpServers' key missing or not a dictionary in {config_path}. Cannot find gateway config."
            )
            return {}

        # 2. Find the gateway's own configuration within 'mcpServers'.
        #    Assumption: The gateway's config is one of the entries here.
        #    Using the first entry for now. A more robust approach might be needed
        #    if multiple top-level entries exist or the key isn't predictable.
        gateway_config_key = next(iter(top_level_mcp_servers), None)
        if not gateway_config_key:
            logger.warning(
                f"Top-level 'mcpServers' dictionary in {config_path} is empty. Cannot find gateway config."
            )
            return {}

        gateway_config = top_level_mcp_servers.get(gateway_config_key)
        if not isinstance(gateway_config, dict):
            logger.warning(
                f"Gateway config entry '{gateway_config_key}' in 'mcpServers' is not a dictionary in {config_path}."
            )
            return {}

        # 3. Extract the nested 'servers' key from the gateway's config
        nested_servers_config = gateway_config.get(Constants.SERVERS, {})
        if not isinstance(nested_servers_config, dict):
            logger.warning(
                f"Nested '{Constants.SERVERS}' key within '{gateway_config_key}' config in {config_path} is not a dictionary. Treating as empty."
            )
            return {}  # Return empty dict if nested 'servers' isn't a dict

        if not nested_servers_config:
            logger.warning(
                f"Nested '{Constants.SERVERS}' key within '{gateway_config_key}' config in {config_path} is missing or empty. No proxied servers will be configured."
            )
            # Fall through to return the (potentially empty) nested_servers_config

        logger.info(
            f"Successfully extracted nested '{Constants.SERVERS}' config for proxied servers from {config_path}."
        )
        # Return the extracted dict directly
        return nested_servers_config

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {config_path}: {e}")
        raise  # Re-raise JSON error
    except StopIteration:
        # Handle case where iter(top_level_mcp_servers) is empty
        logger.warning(
            f"Top-level 'mcpServers' dictionary in {config_path} is empty. Cannot find gateway config."
        )
        return {}
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while loading/parsing config from {config_path}: {e}",
            exc_info=True,  # Add traceback for unexpected errors
        )
        # Decide on behavior: re-raise or return default?
        # Returning default might hide issues, re-raising makes failure explicit.
        raise  # Re-raise other unexpected errors for now


def load_config(mcp_json_path: str) -> Dict[str, Any]:
    """Loads the MCP gateway's proxied server configurations.

    Uses the provided mcp_json_path to locate the config file,
    finds the gateway's own config within the top-level
    'mcpServers' dict, and extracts the *nested* "servers" key from it,
    which contains the definitions of the servers to be proxied.

    Args:
        mcp_json_path: Path to the mcp.json configuration file.

    Returns:
        A dictionary where keys are the names of the proxied servers (e.g.,
        "fetch") and values are their configuration dictionaries.
        Returns an empty dictionary {} if no config file is found, the file
        is invalid, or the required keys ("mcpServers", gateway config,
        nested "servers") are missing/empty/invalid.

    Raises:
        json.JSONDecodeError: If the configuration file is not valid JSON.
        Exception: For other unexpected errors during loading.
    """
    logger.info(f"Using configuration file at: {mcp_json_path}")
    found_path = find_config_file(mcp_json_path)

    if found_path:
        return load_servers_config_from_path(found_path)
    else:
        logger.warning(
            f"Configuration file not found at specified path: {mcp_json_path}"
        )
        logger.warning("Using empty configuration for proxied servers.")
        return {}  # Return empty dict


def get_tool_params_description(tool: types.Tool) -> List[Tuple[str, Any, str]]:
    param_signatures = []

    # Tool has inputSchema (JSON Schema) instead of arguments
    if hasattr(tool, "inputSchema") and tool.inputSchema:
        # Try to extract properties from JSON Schema
        properties = tool.inputSchema.get("properties", {})
        for param_name, param_schema in properties.items():
            param_type = Any  # Default type
            param_description = param_schema.get("description", "")

            # Map JSON Schema types to Python types
            json_type = param_schema.get("type")
            if json_type:
                type_mapping = {
                    "string": str,
                    "integer": int,
                    "boolean": bool,
                    "number": float,
                    "object": Dict[str, Any],
                    "array": List[Any],
                }
                param_type = type_mapping.get(json_type, Any)

            param_signatures.append((param_name, param_type, param_description))
    return param_signatures
