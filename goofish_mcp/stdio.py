import json
import sys
from typing import Any, Dict, Optional


def _readline() -> Optional[str]:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return line.decode("utf-8", errors="replace")


def read_message() -> Optional[Dict[str, Any]]:
    """Read a single JSON-RPC message (one JSON object per line).

    Codex's `rmcp` transport uses newline-delimited JSON for stdio.
    """
    while True:
        line = _readline()
        if line is None:
            return None
        stripped = line.strip()
        if stripped == "":
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            # Keep MCP stdout clean; log parse issues to stderr and keep reading.
            sys.stderr.write(f"[goofish-mcp] invalid json line ignored: {stripped[:200]}\n")
            sys.stderr.flush()


def write_message(message: Dict[str, Any]) -> None:
    """Write a single JSON-RPC message (one JSON object per line)."""
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(data.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

