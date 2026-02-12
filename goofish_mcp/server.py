import asyncio
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

from goofish_mcp import __version__
from goofish_mcp.stdio import read_message, write_message
from goofish_mcp.xianyu import RiskControlError, get_listing, search, write_login_state


def _jsonrpc_result(msg_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str, data: Optional[dict] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _tool_text(payload: Any, is_error: bool = False) -> Dict[str, Any]:
    # Keep result machine-readable for Codex: always JSON.
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "xianyu_write_login_state",
        "description": (
            "Write Xianyu/Goofish login-state JSON (exported from the browser extension) to a local file. "
            "This state file is used by other tools to access goofish.com as a logged-in user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The login-state JSON content."},
                "path": {
                    "type": "string",
                    "description": (
                        "Target path to write. Default is env GOOFISH_STATE_FILE or `state/xianyu_state.json`."
                    ),
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "xianyu_search",
        "description": "Search Goofish (Xianyu) listings by keyword and return structured candidates with URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords."},
                "limit": {
                    "type": "integer",
                    "description": "Max items returned (1-50).",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
                "state_file": {"type": "string", "description": "Override login-state JSON file path."},
                "headless": {"type": "boolean", "description": "Run browser headless (default from env)."},
                "proxy_server": {"type": "string", "description": "Playwright proxy server, e.g. http://127.0.0.1:7890"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "xianyu_get_listing",
        "description": "Open a listing URL and return detail fields (title/desc/images/seller/raw).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Listing URL (https://www.goofish.com/...)"},
                "state_file": {"type": "string", "description": "Override login-state JSON file path."},
                "headless": {"type": "boolean", "description": "Run browser headless (default from env)."},
                "proxy_server": {"type": "string", "description": "Playwright proxy server, e.g. http://127.0.0.1:7890"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "xianyu_healthcheck",
        "description": "Check runtime dependencies and default login-state file presence.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _handle_initialize(msg: Dict[str, Any]) -> Dict[str, Any]:
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    protocol_version = params.get("protocolVersion") or "2024-11-05"
    return _jsonrpc_result(
        msg_id,
        {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "goofish-mcp", "version": __version__},
        },
    )


def _handle_tools_list(msg: Dict[str, Any]) -> Dict[str, Any]:
    return _jsonrpc_result(msg.get("id"), {"tools": TOOLS})


def _handle_tools_call(msg: Dict[str, Any]) -> Dict[str, Any]:
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}

    try:
        if name == "xianyu_write_login_state":
            content = arguments.get("content")
            path = arguments.get("path")
            if not isinstance(content, str):
                return _jsonrpc_result(msg_id, _tool_text({"error": "content must be a string"}, is_error=True))
            target = write_login_state(content=content, path=path)
            return _jsonrpc_result(msg_id, _tool_text({"ok": True, "path": target}))

        if name == "xianyu_search":
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip():
                return _jsonrpc_result(msg_id, _tool_text({"error": "query must be a non-empty string"}, is_error=True))
            limit = arguments.get("limit", 20)
            state_file = arguments.get("state_file")
            headless = arguments.get("headless")
            proxy_server = arguments.get("proxy_server")
            result = asyncio.run(
                search(
                    query=query.strip(),
                    limit=int(limit) if isinstance(limit, (int, float, str)) else 20,
                    state_file=state_file if isinstance(state_file, str) else None,
                    headless=headless if isinstance(headless, bool) else None,
                    proxy_server=proxy_server if isinstance(proxy_server, str) else None,
                )
            )
            return _jsonrpc_result(msg_id, _tool_text(result))

        if name == "xianyu_get_listing":
            url = arguments.get("url")
            if not isinstance(url, str) or not url.strip():
                return _jsonrpc_result(msg_id, _tool_text({"error": "url must be a non-empty string"}, is_error=True))
            state_file = arguments.get("state_file")
            headless = arguments.get("headless")
            proxy_server = arguments.get("proxy_server")
            result = asyncio.run(
                get_listing(
                    url=url.strip(),
                    state_file=state_file if isinstance(state_file, str) else None,
                    headless=headless if isinstance(headless, bool) else None,
                    proxy_server=proxy_server if isinstance(proxy_server, str) else None,
                )
            )
            return _jsonrpc_result(msg_id, _tool_text(result))

        if name == "xianyu_healthcheck":
            state_file = os.getenv("GOOFISH_STATE_FILE") or os.path.join("state", "xianyu_state.json")
            playwright_available = True
            try:
                import playwright  # type: ignore  # noqa: F401
            except Exception:
                playwright_available = False

            return _jsonrpc_result(
                msg_id,
                _tool_text(
                    {
                        "ok": True,
                        "playwright_installed": playwright_available,
                        "default_state_file": state_file,
                        "default_state_file_exists": os.path.exists(state_file),
                        "env": {
                            "GOOFISH_STATE_FILE": os.getenv("GOOFISH_STATE_FILE"),
                            "GOOFISH_RUN_HEADLESS": os.getenv("GOOFISH_RUN_HEADLESS"),
                            "GOOFISH_BROWSER_CHANNEL": os.getenv("GOOFISH_BROWSER_CHANNEL"),
                        },
                    }
                ),
            )

        return _jsonrpc_error(msg_id, -32601, f"Unknown tool: {name!r}")
    except RiskControlError as e:
        return _jsonrpc_result(
            msg_id,
            _tool_text(
                {
                    "error": "risk_control_blocked",
                    "message": str(e),
                    "hint": "Try updating login-state JSON and/or run with headless=false (env GOOFISH_RUN_HEADLESS=false).",
                },
                is_error=True,
            ),
        )
    except Exception as e:
        return _jsonrpc_result(
            msg_id,
            _tool_text(
                {
                    "error": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(limit=8),
                },
                is_error=True,
            ),
        )


def serve() -> None:
    # Important: never print to stdout here (stdout is reserved for MCP messages).
    # Stderr is safe for human-readable logs.
    sys.stderr.write(f"goofish-mcp {__version__}: started (stdio). Waiting for MCP client...\n")
    sys.stderr.flush()
    while True:
        msg = read_message()
        if msg is None:
            return

        method = msg.get("method")
        msg_id = msg.get("id")

        # Notifications (no id) do not require response.
        if msg_id is None:
            continue

        if method == "initialize":
            write_message(_handle_initialize(msg))
            continue
        if method == "tools/list":
            write_message(_handle_tools_list(msg))
            continue
        if method == "tools/call":
            write_message(_handle_tools_call(msg))
            continue
        if method == "ping":
            write_message(_jsonrpc_result(msg_id, {}))
            continue

        # Resources/Prompts are intentionally not implemented in this minimal fork.
        # Still, we return empty lists for compatibility with MCP clients that probe them.
        if method == "resources/list":
            write_message(_jsonrpc_result(msg_id, {"resources": [], "nextCursor": None}))
            continue
        if method == "resources/templates/list":
            write_message(_jsonrpc_result(msg_id, {"resourceTemplates": [], "nextCursor": None}))
            continue
        if method == "prompts/list":
            write_message(_jsonrpc_result(msg_id, {"prompts": [], "nextCursor": None}))
            continue

        write_message(_jsonrpc_error(msg_id, -32601, f"Method not found: {method!r}"))


__all__ = ["serve"]
