import inspect
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

from mcp_gateway.plugins.base import (
    Plugin,
    PluginContext,
    GuardrailPlugin,
    TracingPlugin,
)

logger = logging.getLogger(__name__)

# Type variable for plugins
PluginT = TypeVar("PluginT", bound=Plugin)

# Plugin registry to store all registered plugins
_PLUGIN_REGISTRY: Dict[str, List[Type[Plugin]]] = {
    GuardrailPlugin.plugin_type: [],
    TracingPlugin.plugin_type: [],
}

# Plugin name to class mapping - helps with lookups
_PLUGIN_NAME_TO_INFO: Dict[str, Dict[str, Any]] = {}

# Flag to track if plugins have been discovered
_PLUGINS_DISCOVERED = False


def register_plugin(plugin_cls: Type[PluginT]) -> Type[PluginT]:
    """Decorator for registering plugin classes.

    Args:
        plugin_cls: The plugin class to register

    Returns:
        The original plugin class
    """
    plugin_type = getattr(plugin_cls, "plugin_type", None)

    if not plugin_type:
        logger.warning(
            f"Plugin {plugin_cls.__name__} has no plugin_type. Skipping registration."
        )
        return plugin_cls

    # Add plugin type to registry if not exists
    if plugin_type not in _PLUGIN_REGISTRY:
        _PLUGIN_REGISTRY[plugin_type] = []

    # Register the plugin class
    _PLUGIN_REGISTRY[plugin_type].append(plugin_cls)

    # Store both class name and plugin_name attribute as lookup keys
    plugin_class_name = plugin_cls.__name__.lower()
    _PLUGIN_NAME_TO_INFO[plugin_class_name] = {
        "type": plugin_type,
        "class": plugin_cls,
    }

    # Also register by plugin_name attribute if different
    plugin_attr_name = getattr(plugin_cls, "plugin_name", "").lower()
    if plugin_attr_name and plugin_attr_name != plugin_class_name:
        _PLUGIN_NAME_TO_INFO[plugin_attr_name] = {
            "type": plugin_type,
            "class": plugin_cls,
        }

    logger.info(f"Registered plugin: {plugin_cls.__name__} (type: {plugin_type})")

    return plugin_cls


def discover_plugins():
    """Discover plugins by importing plugin modules via their __init__.py files.

    This simplified approach relies on the imports already defined in the package __init__.py files
    rather than using dynamic module discovery.
    """
    global _PLUGINS_DISCOVERED

    if _PLUGINS_DISCOVERED:
        return

    logger.debug("Discovering plugins...")

    # Import plugin packages to trigger registration via their __init__.py files
    # The __init__.py files should already import all plugin modules
    try:
        import mcp_gateway.plugins.guardrails
        import mcp_gateway.plugins.tracing

        logger.info(f"Discovered {len(_PLUGIN_NAME_TO_INFO)} plugins")
        _PLUGINS_DISCOVERED = True
    except ImportError as e:
        logger.error(f"Failed to import plugin packages: {e}")


def get_plugin_type(plugin_name: str) -> Optional[str]:
    """Get the plugin type for a given plugin name.

    Args:
        plugin_name: The name of the plugin to look up

    Returns:
        The plugin type or None if not found
    """
    # Make sure plugins are discovered
    discover_plugins()

    # Normalize the plugin name
    plugin_name_lower = plugin_name.lower()

    # Look up the plugin type
    plugin_info = _PLUGIN_NAME_TO_INFO.get(plugin_name_lower)
    if plugin_info:
        return plugin_info["type"]

    return None


class PluginManager:
    """Manages plugins using the Registry Pattern."""

    def __init__(
        self,
        enabled_types: Optional[List[str]] = None,
        enabled_plugins: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Initializes the PluginManager with configured plugins.

        Args:
            enabled_types: List of plugin types to enable (e.g., ['guardrail', 'tracing']).
                          If None or empty, no plugins will be loaded.
            enabled_plugins: Dictionary mapping plugin types to lists of plugin names to enable
                          (e.g., {'guardrail': ['basic', 'lasso']}).
                          If a type has an empty list or contains 'all', all plugins of that type are enabled.
        """
        # Ensure plugins are discovered before initialization
        discover_plugins()

        self.enabled_types = enabled_types or []
        self.enabled_plugins = enabled_plugins or {}

        # Dictionary to store instantiated plugin objects
        self._plugins: Dict[str, List[Plugin]] = {}

        # Load enabled plugins
        self._load_plugins()

    def _load_plugins(self) -> None:
        """Load and instantiate all enabled plugins from the registry."""
        if not self.enabled_types:
            logger.info("No plugin types enabled.")
            return

        # Initialize plugin containers
        for plugin_type in _PLUGIN_REGISTRY:
            self._plugins[plugin_type] = []

        # Load enabled plugin types
        for plugin_type in self.enabled_types:
            if plugin_type not in _PLUGIN_REGISTRY:
                logger.warning(f"Unknown plugin type: {plugin_type}")
                continue

            # Get enabled plugin names for this type
            enabled_names = self.enabled_plugins.get(plugin_type, [])
            load_all_of_type = not enabled_names or "all" in enabled_names

            # Load plugins of this type
            for plugin_cls in _PLUGIN_REGISTRY[plugin_type]:
                # Try matching by class name or plugin_name attribute
                plugin_name = plugin_cls.__name__.lower()
                plugin_attr_name = getattr(plugin_cls, "plugin_name", "").lower()

                # Check if plugin should be loaded
                should_load = load_all_of_type
                if not should_load:
                    for enabled in enabled_names:
                        enabled_lower = enabled.lower()
                        if (
                            enabled_lower == plugin_name
                            or enabled_lower == plugin_attr_name
                        ):
                            should_load = True
                            break

                if not should_load:
                    logger.debug(
                        f"Skipping plugin {plugin_cls.__name__} - not explicitly enabled"
                    )
                    continue

                # Instantiate and load the plugin
                try:
                    plugin_instance = plugin_cls()
                    plugin_instance.load({})  # Empty config by default
                    self._plugins[plugin_type].append(plugin_instance)
                    logger.info(
                        f"Loaded plugin: {plugin_cls.__name__} (type: {plugin_type})"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to load plugin {plugin_cls.__name__}: {e}",
                        exc_info=True,
                    )

        # Log summary of loaded plugins
        for p_type, p_list in self._plugins.items():
            if p_type in self.enabled_types:
                logger.info(f"Loaded {len(p_list)} plugins of type '{p_type}'")

    def get_plugins(self, plugin_type: str) -> List[Plugin]:
        """Returns loaded plugins of a specific type.

        Args:
            plugin_type: Type of plugins to return

        Returns:
            List of loaded plugins of the specified type
        """
        return self._plugins.get(plugin_type, [])

    async def process_request(self, context: PluginContext) -> Optional[Dict[str, Any]]:
        """Processes a request through all relevant plugins.

        Args:
            context: The plugin context containing request information

        Returns:
            The modified arguments after all plugins, or None if blocked
        """
        current_args = context.arguments

        # Run Tracing plugins (for monitoring)
        for plugin in self.get_plugins(TracingPlugin.plugin_type):
            try:
                context_for_plugin = PluginContext(
                    server_name=context.server_name,
                    capability_type=context.capability_type,
                    capability_name=context.capability_name,
                    arguments=current_args,
                    mcp_context=context.mcp_context,
                )

                if inspect.iscoroutinefunction(plugin.process_request):
                    await plugin.process_request(context_for_plugin)
                else:
                    plugin.process_request(context_for_plugin)
            except Exception as e:
                logger.error(
                    f"Error in tracing request plugin {plugin.__class__.__name__}: {e}",
                    exc_info=True,
                )

        # Run Guardrail plugins (can modify or block)
        for plugin in self.get_plugins(GuardrailPlugin.plugin_type):
            if current_args is None:  # If a previous guardrail blocked
                break

            try:
                context_for_plugin = PluginContext(
                    server_name=context.server_name,
                    capability_type=context.capability_type,
                    capability_name=context.capability_name,
                    arguments=current_args,
                    mcp_context=context.mcp_context,
                )

                if inspect.iscoroutinefunction(plugin.process_request):
                    current_args = await plugin.process_request(context_for_plugin)
                else:
                    current_args = plugin.process_request(context_for_plugin)
            except Exception as e:
                # Fail closed: a guardrail exception must block the request,
                # not leave the pre-exception args in place for forwarding.
                logger.error(
                    f"Error in guardrail request plugin {plugin.__class__.__name__}: {e}",
                    exc_info=True,
                )
                return None

        return current_args

    async def process_response(self, context: PluginContext) -> Any:
        """Processes a response through all relevant plugins.

        Args:
            context: The plugin context containing response information

        Returns:
            The modified response after all plugins
        """
        current_response = context.response

        # Run Guardrail plugins for response (can modify)
        for plugin in self.get_plugins(GuardrailPlugin.plugin_type):
            try:
                context_for_plugin = PluginContext(
                    server_name=context.server_name,
                    capability_type=context.capability_type,
                    capability_name=context.capability_name,
                    arguments=context.arguments,
                    response=current_response,
                    mcp_context=context.mcp_context,
                )

                if inspect.iscoroutinefunction(plugin.process_response):
                    current_response = await plugin.process_response(context_for_plugin)
                else:
                    current_response = plugin.process_response(context_for_plugin)
            except Exception as e:
                # Fail closed (#16): a guardrail that raises (including an
                # intentional SanitizationError) must not leave the upstream
                # response bound for forwarding. Re-raise so callers decide
                # how to surface the block; do not continue the pipeline.
                logger.error(
                    f"Error in guardrail response plugin {plugin.__class__.__name__}: {e}",
                    exc_info=True,
                )
                raise

        # Run Tracing plugins for response (for monitoring)
        for plugin in self.get_plugins(TracingPlugin.plugin_type):
            try:
                context_for_plugin = PluginContext(
                    server_name=context.server_name,
                    capability_type=context.capability_type,
                    capability_name=context.capability_name,
                    arguments=context.arguments,
                    response=current_response,
                    mcp_context=context.mcp_context,
                )

                if inspect.iscoroutinefunction(plugin.process_response):
                    await plugin.process_response(context_for_plugin)
                else:
                    plugin.process_response(context_for_plugin)
            except Exception as e:
                logger.error(
                    f"Error in tracing response plugin {plugin.__class__.__name__}: {e}",
                    exc_info=True,
                )

        return current_response
