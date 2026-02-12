# Repository Guidelines (Minimal MCP Fork)

## Scope

This fork intentionally removes the original Web UI / scheduler / AI / notification stack.
The only supported feature set is:

- Import/login-state JSON (exported from browser extension)
- Search listings
- Fetch listing detail
- Expose the above as an MCP server over stdio

## Project Layout

- MCP server (Python): `goofish_mcp/`
- npx launcher: `package.json`, `bin/goofish-mcp`
- Login-state export helper (optional): `chrome-extension/`

## Run Locally

```bash
pip install -r requirements.txt
playwright install chromium
python3 -m goofish_mcp
```

## Coding Style

- Keep dependencies minimal; avoid pulling in heavy MCP SDKs unless needed.
- Prefer returning machine-readable JSON in tool results (so Codex can reason on it).
- Handle missing dependencies gracefully (server should start even if Playwright isn't installed).

