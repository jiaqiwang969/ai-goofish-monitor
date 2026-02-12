import asyncio
import contextlib
import json
import os
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search"
DETAIL_API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail"


class RiskControlError(RuntimeError):
    """Raised when Xianyu/Goofish risk-control blocks automation."""


def _as_bool(value: Optional[object], default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_state_file(state_file: Optional[str]) -> str:
    path = state_file or os.getenv("GOOFISH_STATE_FILE") or os.path.join("state", "xianyu_state.json")
    return path


def _load_json_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clean_kwargs(options: dict) -> dict:
    return {k: v for k, v in options.items() if v is not None}


def _looks_like_mobile(ua: str) -> Optional[bool]:
    if not ua:
        return None
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return True
    if "windows" in ua_lower or "macintosh" in ua_lower:
        return False
    return None


def _build_context_overrides(snapshot: dict) -> dict:
    env = snapshot.get("env") or {}
    headers = snapshot.get("headers") or {}
    navigator = env.get("navigator") or {}
    screen = env.get("screen") or {}
    intl = env.get("intl") or {}

    overrides: Dict[str, Any] = {}

    ua = headers.get("User-Agent") or headers.get("user-agent") or navigator.get("userAgent")
    if ua:
        overrides["user_agent"] = ua

    accept_language = headers.get("Accept-Language") or headers.get("accept-language")
    locale = None
    if accept_language:
        locale = accept_language.split(",")[0].strip()
    elif navigator.get("language"):
        locale = navigator["language"]
    if locale:
        overrides["locale"] = locale

    tz = intl.get("timeZone")
    if tz:
        overrides["timezone_id"] = tz

    width = screen.get("width")
    height = screen.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        overrides["viewport"] = {"width": int(width), "height": int(height)}

    dpr = screen.get("devicePixelRatio")
    if isinstance(dpr, (int, float)):
        overrides["device_scale_factor"] = float(dpr)

    touch_points = navigator.get("maxTouchPoints")
    if isinstance(touch_points, (int, float)):
        overrides["has_touch"] = touch_points > 0

    mobile_flag = _looks_like_mobile(ua or "")
    if mobile_flag is not None:
        overrides["is_mobile"] = mobile_flag

    return _clean_kwargs(overrides)


def _build_extra_headers(raw_headers: Optional[dict]) -> dict:
    if not raw_headers:
        return {}
    excluded = {"cookie", "content-length"}
    headers = {}
    for key, value in raw_headers.items():
        if not key or key.lower() in excluded or value is None:
            continue
        headers[key] = value
    return headers


def _default_context_options() -> dict:
    # Mobile-ish defaults; can be overridden by enhanced snapshot export.
    return {
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
            "Mobile Safari/537.36"
        ),
        "viewport": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "permissions": ["geolocation"],
        "geolocation": {"longitude": 121.4737, "latitude": 31.2304},
        "color_scheme": "light",
    }


async def _random_sleep(min_seconds: float, max_seconds: float) -> None:
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


def _parse_price_to_number(price: str) -> Optional[float]:
    if not price:
        return None
    s = str(price).strip()
    # Common formats: "¥123", "123", "¥1.2万"
    s = s.replace("当前价", "").strip()
    s = s.replace("¥", "").strip()
    if s.endswith("万"):
        try:
            return float(s[:-1]) * 10000.0
        except ValueError:
            return None
    s = re.sub(r"[^\d.]+", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pick_channel() -> Optional[str]:
    # If user explicitly sets a channel, respect it (e.g., "chrome", "msedge").
    channel = os.getenv("GOOFISH_BROWSER_CHANNEL")
    if channel:
        return channel.strip()
    return None


async def _new_browser_and_context(state_file: str, headless: bool, proxy_server: Optional[str]) -> Any:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Python dependency missing: playwright. Install it first: `pip install playwright` "
            "then install browser: `playwright install chromium`."
        ) from e

    snapshot = _load_json_file(state_file)

    # Start playwright + browser.
    p = await async_playwright().start()
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
    ]

    launch_kwargs: Dict[str, Any] = {"headless": headless, "args": launch_args}
    if proxy_server:
        launch_kwargs["proxy"] = {"server": proxy_server}
    channel = _pick_channel()
    if channel:
        launch_kwargs["channel"] = channel

    browser = await p.chromium.launch(**launch_kwargs)

    context_kwargs = _default_context_options()
    storage_state_arg: Any = state_file

    if isinstance(snapshot, dict):
        # Enhanced extension export format (env/headers/...).
        if any(k in snapshot for k in ("env", "headers", "page", "storage")):
            storage_state_arg = {"cookies": snapshot.get("cookies", [])}
            context_kwargs.update(_build_context_overrides(snapshot))
            extra_headers = _build_extra_headers(snapshot.get("headers"))
            if extra_headers:
                context_kwargs["extra_http_headers"] = extra_headers
        else:
            # Plain Playwright storage_state dict.
            storage_state_arg = snapshot

    context_kwargs = _clean_kwargs(context_kwargs)
    context = await browser.new_context(storage_state=storage_state_arg, **context_kwargs)

    # Basic anti-detection script.
    await context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
        window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}};
        Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({state: Notification.permission})
                : originalQuery(parameters)
        );
        """
    )

    # Return both playwright driver and browser/context for cleanup.
    return p, browser, context


async def _close_browser(p: Any, browser: Any, context: Any) -> None:
    with contextlib.suppress(Exception):
        await context.close()
    with contextlib.suppress(Exception):
        await browser.close()
    with contextlib.suppress(Exception):
        await p.stop()


def _parse_search_results(json_data: dict) -> List[dict]:
    items = (((json_data or {}).get("data") or {}).get("resultList") or [])
    parsed: List[dict] = []

    for item in items:
        main = (((((item or {}).get("data") or {}).get("item") or {}).get("main") or {}).get("exContent") or {})
        click_args = (
            (((((item or {}).get("data") or {}).get("item") or {}).get("main") or {}).get("clickParam") or {})
            .get("args")
            or {}
        )

        title = main.get("title") or "未知标题"
        price_parts = main.get("price")
        if isinstance(price_parts, list):
            price_text = "".join(
                [str(p.get("text", "")) for p in price_parts if isinstance(p, dict)]
            ).replace("当前价", "").strip()
        else:
            price_text = str(price_parts or "").strip()

        area = main.get("area") or "地区未知"
        seller = main.get("userNickName") or "匿名卖家"
        raw_link = (
            (((((item or {}).get("data") or {}).get("item") or {}).get("main") or {}).get("targetUrl") or "")
        )
        image_url = main.get("picUrl") or ""
        pub_ts = str(click_args.get("publishTime") or "")
        item_id = main.get("itemId") or ""
        wants = click_args.get("wantNum")
        original_price = main.get("oriPrice")

        tags: List[str] = []
        if click_args.get("tag") == "freeship":
            tags.append("包邮")
        r1_tags = (((main.get("fishTags") or {}).get("r1") or {}).get("tagList") or [])
        if isinstance(r1_tags, list):
            for tag_item in r1_tags:
                content = (((tag_item or {}).get("data") or {}).get("content") or "")
                if "验货宝" in content:
                    tags.append("验货宝")

        publish_time = "未知时间"
        if pub_ts.isdigit():
            try:
                publish_time = datetime.fromtimestamp(int(pub_ts) / 1000).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        url = raw_link.replace("fleamarket://", "https://www.goofish.com/")

        parsed.append(
            {
                "title": title,
                "price": price_text,
                "price_number": _parse_price_to_number(price_text),
                "original_price": original_price,
                "wants": wants,
                "tags": tags,
                "ship_from": area,
                "seller": seller,
                "url": url,
                "publish_time": publish_time,
                "item_id": item_id,
                "image_url": image_url,
            }
        )

    return parsed


async def search(
    query: str,
    limit: int = 20,
    state_file: Optional[str] = None,
    headless: Optional[bool] = None,
    proxy_server: Optional[str] = None,
) -> Dict[str, Any]:
    state_path = _resolve_state_file(state_file)
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"login-state JSON not found: {state_path}. Use tool `xianyu_write_login_state` first "
            "or set env `GOOFISH_STATE_FILE`."
        )

    if headless is None:
        headless = _as_bool(os.getenv("GOOFISH_RUN_HEADLESS"), default=True)

    p, browser, context = await _new_browser_and_context(state_path, headless=headless, proxy_server=proxy_server)

    page = await context.new_page()
    try:
        await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
        await _random_sleep(0.8, 1.8)
        await page.evaluate("window.scrollBy(0, Math.random() * 400 + 150)")
        await _random_sleep(0.6, 1.6)

        params = {"q": query}
        search_url = f"https://www.goofish.com/search?{urlencode(params)}"

        async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=30000) as response_info:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        resp = await response_info.value
        data = await resp.json()

        # Quick risk-control detection signals in API response.
        ret = str(data.get("ret") or "")
        if "FAIL_SYS_USER_VALIDATE" in ret:
            raise RiskControlError("FAIL_SYS_USER_VALIDATE")

        items = _parse_search_results(data)
        if limit and isinstance(limit, int):
            items = items[: max(1, min(int(limit), 50))]
        return {"query": query, "search_url": search_url, "count": len(items), "items": items}
    except Exception as e:
        # Avoid importing playwright at module import-time; detect timeout by name.
        if e.__class__.__name__ == "TimeoutError":
            raise TimeoutError(f"timeout while searching query={query!r}") from e
        raise
    finally:
        with contextlib.suppress(Exception):
            await page.close()
        await _close_browser(p, browser, context)


def _parse_listing_detail(detail_json: dict, url: str) -> Dict[str, Any]:
    data = detail_json.get("data") or {}
    item_do = data.get("itemDO") or {}
    seller_do = data.get("sellerDO") or {}

    title = item_do.get("title") or item_do.get("itemTitle") or item_do.get("name") or ""
    desc = item_do.get("desc") or item_do.get("description") or ""

    image_infos = item_do.get("imageInfos") or []
    images: List[str] = []
    if isinstance(image_infos, list):
        for img in image_infos:
            if isinstance(img, dict) and img.get("url"):
                images.append(img["url"])

    want_cnt = item_do.get("wantCnt")
    browse_cnt = item_do.get("browseCnt")

    seller_id = seller_do.get("sellerId") or seller_do.get("userId")
    seller_nick = seller_do.get("nick") or seller_do.get("userNick") or seller_do.get("sellerNick")
    zhima = ((seller_do.get("zhimaLevelInfo") or {}) if isinstance(seller_do.get("zhimaLevelInfo"), dict) else {})
    zhima_level = zhima.get("levelName")

    return {
        "url": url,
        "title": title,
        "description": desc,
        "images": images,
        "want_cnt": want_cnt,
        "browse_cnt": browse_cnt,
        "seller": {
            "seller_id": seller_id,
            "nick": seller_nick,
            "zhima_level": zhima_level,
            "raw": seller_do,
        },
        "raw": item_do,
    }


async def get_listing(
    url: str,
    state_file: Optional[str] = None,
    headless: Optional[bool] = None,
    proxy_server: Optional[str] = None,
) -> Dict[str, Any]:
    state_path = _resolve_state_file(state_file)
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"login-state JSON not found: {state_path}. Use tool `xianyu_write_login_state` first "
            "or set env `GOOFISH_STATE_FILE`."
        )

    if headless is None:
        headless = _as_bool(os.getenv("GOOFISH_RUN_HEADLESS"), default=True)

    p, browser, context = await _new_browser_and_context(state_path, headless=headless, proxy_server=proxy_server)

    page = await context.new_page()
    try:
        await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
        await _random_sleep(0.8, 1.8)

        async with page.expect_response(lambda r: DETAIL_API_URL_PATTERN in r.url, timeout=30000) as detail_info:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        resp = await detail_info.value
        detail_json = await resp.json()

        ret = str(detail_json.get("ret") or "")
        if "FAIL_SYS_USER_VALIDATE" in ret:
            raise RiskControlError("FAIL_SYS_USER_VALIDATE")

        return _parse_listing_detail(detail_json, url=url)
    except Exception as e:
        if e.__class__.__name__ == "TimeoutError":
            raise TimeoutError(f"timeout while opening url={url!r}") from e
        raise
    finally:
        with contextlib.suppress(Exception):
            await page.close()
        await _close_browser(p, browser, context)


def write_login_state(content: str, path: Optional[str] = None) -> str:
    # Validate JSON first.
    try:
        json.loads(content)
    except Exception as e:
        raise ValueError("content is not valid JSON") from e

    target = path or _resolve_state_file(None)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    with open(target, "w", encoding="utf-8") as f:
        f.write(content)

    return target
