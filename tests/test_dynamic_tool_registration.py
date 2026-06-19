import inspect
import asyncio

from mcp.server.fastmcp import FastMCP
from mcp import types

from mcp_gateway.gateway import register_dynamic_tool


class RecordingFastMCP:
    def __init__(self):
        self.registered = {}

    def tool(self, name=None, description=None):
        def decorator(fn):
            self.registered[name] = fn
            return fn

        return decorator


class RecordingProxiedServer:
    def __init__(self):
        self.calls = []

    async def call_tool(self, **kwargs):
        self.calls.append(kwargs)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")]
        )


def test_dynamic_tool_accepts_json_schema_names_that_are_not_python_identifiers():
    asyncio.run(_check_dynamic_tool_accepts_json_schema_names_that_are_not_python_identifiers())


async def _check_dynamic_tool_accepts_json_schema_names_that_are_not_python_identifiers():
    gateway_mcp = RecordingFastMCP()
    proxied_server = RecordingProxiedServer()
    tool = types.Tool(
        name="api-get-block-children",
        description="Fetch children",
        inputSchema={
            "type": "object",
            "properties": {
                "Notion-Version": {"type": "string"},
                "1st-page": {"type": "integer"},
                "class": {"type": "string"},
            },
            "required": ["Notion-Version"],
        },
    )

    await register_dynamic_tool(
        gateway_mcp,
        "notion",
        tool,
        proxied_server,
        plugin_manager=None,
    )

    handler = gateway_mcp.registered["notion_api-get-block-children"]
    signature = inspect.signature(handler)

    assert "Notion_Version" in signature.parameters
    assert "param_1st_page" in signature.parameters
    assert "param_class" in signature.parameters
    assert signature.parameters["Notion_Version"].default is inspect.Parameter.empty
    assert signature.parameters["param_1st_page"].default is None
    assert signature.parameters["param_class"].default is None

    await handler(
        Notion_Version="2025-06-20",
        param_1st_page=3,
        param_class="page",
    )

    assert proxied_server.calls[0]["name"] == "api-get-block-children"
    assert proxied_server.calls[0]["arguments"] == {
        "Notion-Version": "2025-06-20",
        "1st-page": 3,
        "class": "page",
    }


def test_dynamic_tool_omits_unset_optional_arguments():
    asyncio.run(_check_dynamic_tool_omits_unset_optional_arguments())


async def _check_dynamic_tool_omits_unset_optional_arguments():
    gateway_mcp = RecordingFastMCP()
    proxied_server = RecordingProxiedServer()
    tool = types.Tool(
        name="search",
        description="Search",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "start-cursor": {"type": "string"},
            },
            "required": ["query"],
        },
    )

    await register_dynamic_tool(
        gateway_mcp,
        "notion",
        tool,
        proxied_server,
        plugin_manager=None,
    )

    handler = gateway_mcp.registered["notion_search"]
    await handler(query="blocks", start_cursor=None)

    assert proxied_server.calls[0]["arguments"] == {"query": "blocks"}


def test_dynamic_tool_schema_uses_original_json_schema_names():
    asyncio.run(_check_dynamic_tool_schema_uses_original_json_schema_names())


async def _check_dynamic_tool_schema_uses_original_json_schema_names():
    gateway_mcp = FastMCP("test")
    proxied_server = RecordingProxiedServer()
    tool = types.Tool(
        name="api-get-block-children",
        description="Fetch children",
        inputSchema={
            "type": "object",
            "properties": {
                "Notion-Version": {"type": "string"},
                "start-cursor": {"type": "string"},
            },
            "required": ["Notion-Version"],
        },
    )

    await register_dynamic_tool(
        gateway_mcp,
        "notion",
        tool,
        proxied_server,
        plugin_manager=None,
    )

    tools = await gateway_mcp.list_tools()
    registered_tool = next(
        tool for tool in tools if tool.name == "notion_api-get-block-children"
    )

    assert registered_tool.inputSchema["properties"].keys() == {
        "Notion-Version",
        "start-cursor",
    }
    assert registered_tool.inputSchema["required"] == ["Notion-Version"]

    await gateway_mcp.call_tool(
        "notion_api-get-block-children",
        {"Notion-Version": "2025-06-20"},
    )

    assert proxied_server.calls[0]["arguments"] == {
        "Notion-Version": "2025-06-20"
    }
