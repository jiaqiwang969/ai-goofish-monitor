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
    """Read a single MCP/JSON-RPC message using Content-Length framing."""
    headers: Dict[str, str] = {}

    while True:
        line = _readline()
        if line is None:
            return None
        # MCP uses \r\n, but be tolerant.
        stripped = line.strip()
        if stripped == "":
            break
        if ":" not in stripped:
            # Skip malformed header line.
            continue
        key, value = stripped.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    length_str = headers.get("content-length")
    if not length_str:
        return None
    try:
        length = int(length_str)
    except ValueError:
        return None

    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    try:
        payload = body.decode("utf-8")
    except UnicodeDecodeError:
        payload = body.decode("utf-8", errors="replace")
    return json.loads(payload)


def write_message(message: Dict[str, Any]) -> None:
    """Write a single MCP/JSON-RPC message using Content-Length framing."""
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

