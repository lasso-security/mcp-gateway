# MCP Gateway Plugin System

This directory contains the plugin system for the MCP Gateway.

## Plugin Types

The MCP Gateway supports the following plugin types:

- **Guardrail Plugins**: These plugins can inspect and modify requests and responses to enforce security policies.
- **Tracing Plugins**: These plugins can monitor requests and responses for logging, metrics, and debugging.

## Creating a New Plugin

To create a new plugin, follow these steps:

1. Decide which plugin type your plugin belongs to (guardrail or tracing).
2. Create a new Python file in the appropriate subdirectory (guardrails or tracing).
3. Implement a class that extends the appropriate base class.
4. Register your plugin using the `@register_plugin` decorator.

### Example Plugin

Here's an example of a simple guardrail plugin:

```python
from typing import Any, Dict, Optional
from mcp_gateway.plugins.base import GuardrailPlugin, PluginContext
from mcp_gateway.plugins.manager import register_plugin

import logging
logger = logging.getLogger(__name__)

@register_plugin
class MyGuardrailPlugin(GuardrailPlugin):
    """A custom guardrail plugin that blocks certain operations."""
    
    # Both class name and plugin_name are used for command-line arguments
    # So either '--plugin MyGuardrail' or '--plugin my-guardrail' will work
    plugin_name = "my-guardrail"
    
    def load(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Configure the plugin with optional settings."""
        logger.info("MyGuardrailPlugin loaded")
    
    def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """Process a request before it's sent to the server."""
        # Return None to block the request, or return modified arguments
        return context.arguments
    
    def process_response(self, context: PluginContext) -> Any:
        """Process a response before it's returned to the client."""
        # Return modified response
        return context.response
```

## Plugin Naming

Plugins can be referenced in two ways:

1. By their class name (e.g., `MyGuardrailPlugin`)
2. By their `plugin_name` attribute (e.g., `my-guardrail`)

Both names are registered during plugin discovery, so either can be used in command-line arguments. For example:

```bash
mcp-gateway -p MyGuardrailPlugin -p basic
# or
mcp-gateway -p my-guardrail -p basic
```

## Best Practices

1. **Unique Naming**: Ensure your plugin's class name and `plugin_name` attribute are unique to avoid conflicts.
2. **Clear Documentation**: Document your plugin's purpose and configuration options.
3. **Error Handling**: Implement robust error handling to avoid breaking the gateway.
4. **Minimal Dependencies**: Keep external dependencies minimal and make them optional when possible.
5. **Efficient Processing**: Minimize processing overhead, especially for plugins that run on every request.

## Plugin Discovery

Plugins are discovered automatically at runtime using Python's package import system. No additional registration is required beyond using the `@register_plugin` decorator.

## Plugin Configuration

Plugins can be configured using the `load()` method, which receives a configuration dictionary. This dictionary is currently empty by default, but future versions of MCP Gateway may provide plugin-specific configuration options.

## Optional: Tool Outcome Attestation (TOA)

Offline delivery-evidence verify is documented in [docs/toa-optional-plugin.md](../../docs/toa-optional-plugin.md). It is not a built-in guardrail in this PR.
