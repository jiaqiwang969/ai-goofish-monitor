"""Minimal Xianyu (Goofish) MCP server.

This fork intentionally keeps only the "hands" part:
- import login-state JSON (from browser extension export)
- search listings
- fetch listing detail

All "buy / don't buy" decisions are meant to be done by the MCP client (Codex).
"""

__version__ = "0.1.2"
