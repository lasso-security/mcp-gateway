"""Minimal stdio MCP server fixture for gateway integration tests."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fixture-server")


@mcp.tool()
def echo(message: str) -> str:
    """Echo the input message."""
    return message


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run()
