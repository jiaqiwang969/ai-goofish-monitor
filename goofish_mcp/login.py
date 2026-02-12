import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _default_state_path() -> str:
    # Prefer codex home location to work out-of-the-box for Codex users.
    return str(Path.home() / ".codex" / "goofish" / "xianyu_state.json")


def _resolve_out_path(path: Optional[str]) -> str:
    if path and path.strip():
        return path.strip()
    env_path = os.getenv("GOOFISH_STATE_FILE")
    if env_path and env_path.strip():
        return env_path.strip()
    return _default_state_path()


async def _async_input(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def run_login(out_path: str, channel: Optional[str] = None) -> str:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright is not ready yet.\n"
            "If you started goofish-mcp via Codex, it will auto-install in the background on first run.\n"
            "Otherwise run:\n"
            "  npx -y --package github:jiaqiwang969/ai-goofish-monitor#main goofish-mcp-setup\n"
            "Then retry login."
        ) from e

    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ]
        launch_kwargs: Dict[str, Any] = {"headless": False, "args": launch_args}
        if channel:
            launch_kwargs["channel"] = channel
        browser = await p.chromium.launch(**launch_kwargs)

        # Keep it simple: default context; user logs in manually.
        context = await browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = await context.new_page()

        try:
            await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            # If first navigation fails, still allow user to interact (e.g. network hiccup).
            pass

        sys.stderr.write("\n[goofish-mcp-login] A browser window is open.\n")
        sys.stderr.write("[goofish-mcp-login] Please complete login in the browser.\n")
        sys.stderr.write("[goofish-mcp-login] When you are done, come back here and press ENTER.\n\n")
        sys.stderr.flush()

        await _async_input("Press ENTER after login succeeds (Ctrl+C to abort): ")

        state = await context.storage_state()
        out.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        await page.close()
        await context.close()
        await browser.close()

    return str(out)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive login helper for goofish-mcp (writes Playwright storage_state JSON).")
    parser.add_argument("--out", help="Output state JSON path. Defaults to $GOOFISH_STATE_FILE or ~/.codex/goofish/xianyu_state.json")
    parser.add_argument("--channel", help="Playwright browser channel, e.g. chrome/msedge (optional).")
    args = parser.parse_args(argv)

    out_path = _resolve_out_path(args.out)

    try:
        saved = asyncio.run(run_login(out_path=out_path, channel=args.channel))
    except KeyboardInterrupt:
        sys.stderr.write("\n[goofish-mcp-login] Aborted.\n")
        return 130
    except Exception as e:
        sys.stderr.write(f"\n[goofish-mcp-login] Failed: {type(e).__name__}: {e}\n")
        return 1

    sys.stderr.write(f"\n[goofish-mcp-login] Saved login state to: {saved}\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
