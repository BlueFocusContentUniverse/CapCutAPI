"""
MCP (Model Context Protocol) Server Package for CapCut API.

This package contains the MCP server implementation that exposes
CapCut API tools through the Model Context Protocol.
"""

from mcp_services.stream_server import create_fastmcp_app

__all__ = ["create_fastmcp_app"]
