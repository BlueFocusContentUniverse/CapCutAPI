#!/usr/bin/env python3
"""
Streaming-capable MCP server for CapCut API tools.

This module re-exports from mcp.stream_server for backward compatibility.
The actual implementation has been moved to the mcp/ package.
"""

# Re-export everything from the new location for backward compatibility
from mcp_local.stream_server import create_fastmcp_app

__all__ = ["create_fastmcp_app"]
