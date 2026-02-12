import json
import sys
from typing import Any, Dict, Optional


_FRAMING: Optional[str] = None  # "line" | "content_length"


def _readline_bytes() -> Optional[bytes]:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    return line


def _decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _parse_content_length(header_line: bytes) -> Optional[int]:
    # Accept both Content-Length and content-length.
    try:
        name, value = header_line.split(b":", 1)
    except ValueError:
        return None
    if name.strip().lower() != b"content-length":
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _read_exact(n: int) -> Optional[bytes]:
    if n <= 0:
        return b""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sys.stdin.buffer.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_content_length_message(first_header_line: bytes) -> Optional[Dict[str, Any]]:
    # Read headers until blank line, then read body of declared length.
    content_length = _parse_content_length(first_header_line.strip())

    while True:
        line = _readline_bytes()
        if line is None:
            return None
        # Header block terminator.
        if line in (b"\n", b"\r\n"):
            break
        if content_length is None:
            content_length = _parse_content_length(line.strip())

    if content_length is None:
        sys.stderr.write("[goofish-mcp] missing Content-Length header; cannot read message\n")
        sys.stderr.flush()
        return None

    body = _read_exact(content_length)
    if body is None:
        return None
    try:
        return json.loads(_decode_utf8(body))
    except json.JSONDecodeError:
        sys.stderr.write("[goofish-mcp] invalid json body ignored (content-length framed)\n")
        sys.stderr.flush()
        return None


def read_message() -> Optional[Dict[str, Any]]:
    """Read a single JSON-RPC message from stdin.

    Supports both:
    - newline-delimited JSON (Codex/rmcp transport)
    - Content-Length framed JSON (LSP-style), for compatibility with other MCP clients
    """
    global _FRAMING
    while True:
        line_bytes = _readline_bytes()
        if line_bytes is None:
            return None
        stripped_bytes = line_bytes.strip()
        if stripped_bytes == b"":
            continue

        # Detect & switch to Content-Length framing if the peer uses it.
        if _FRAMING == "content_length" or stripped_bytes.lower().startswith(b"content-length:"):
            _FRAMING = "content_length"
            msg = _read_content_length_message(line_bytes)
            if msg is None:
                continue
            return msg

        _FRAMING = _FRAMING or "line"
        stripped = _decode_utf8(stripped_bytes)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            # Keep MCP stdout clean; log parse issues to stderr and keep reading.
            sys.stderr.write(f"[goofish-mcp] invalid json line ignored: {stripped[:200]}\n")
            sys.stderr.flush()


def write_message(message: Dict[str, Any]) -> None:
    """Write a single JSON-RPC message to stdout.

    Mirrors the detected framing style (see read_message()).
    """
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if _FRAMING == "content_length":
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return

    # Default: newline-delimited JSON.
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()
