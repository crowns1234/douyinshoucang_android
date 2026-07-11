"""纯 HTTP 采集抖音收藏列表（无需浏览器 / Playwright）。

直接调用 `aweme/v1/web/aweme/favorite/` 接口，分页拉取全部收藏。
适用于 Android Termux、云服务器、GitHub Actions 等无桌面环境。
"""
import json, os, logging, time
import requests

from .utils import BASE_DIR, today_str

logger = logging.getLogger(__name__)

COOKIE_PATH = os.path.join(BASE_DIR, "cookies", "douyin_cookies.json")
STATE_PATH = os.path.join(BASE_DIR, "data", "state.json")
RAW_PATH = os.path.join(BASE_DIR, "data", "favorites_raw.json")

API_URL = "https://www.douyin.com/aweme/v1/web/aweme/favorite/"


def _load_cookies() -> dict:
    """从 cookies/douyin_cookies.json 加载并转成 key→value 字典。"""
    if not os.path.exists(COOKIE_PATH):
        raise FileNotFoundError(f"Cookie 文件不存在：{COOKIE_PATH}")
    with open(COOKIE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # Cookie-Editor 导出的格式：[{"name": "...", "value": "...", ...}, ...]
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw if "name" in c}
    return raw


def _cookie_string(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _get_sec_user_id(cookies: dict) -> str:
    """从各个可能的 cookie 字段提取 sec_user_id。"""
    # 抖音 cookie 里可能存有 sec_uid
    for key in ("sec_user_id", "sec_uid"):
        if key in cookies:
            return cookies[key]
    # msToken 里可能编码了用户信息
    # 回退：请求用户资料接口
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/user/self?showTab=collection",
        "Cookie": _cookie_string(cookies),
    }
    try:
        r = requests.get(
            "https://www.douyin.com/aweme/v1/web/user/profile/self/",
            headers=headers, timeout=15,
        )
        data = r.json()
        uid = data.get("user", {}).get("sec_uid", "")
        if uid:
            return uid
    except Exception:
        pass
    raise RuntimeError("无法获取 sec_user_id，请检查 Cookie 是否有效")


def _scrape_http(cfg: dict) -> list:
    """纯 HTTP 分页拉取收藏列表。"""
    cookies = _load_cookies()
    sec_uid = _get_sec_user_id(cookies)
    ck_str = _cookie_string(cookies)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/user/self?showTab=collection",
        "Cookie": ck_str,
        "Accept": "application/json",
    }

    all_items = []
    max_cursor = 0
    has_more = True
    max_pages = cfg["collection"].get("scroll_times", 12)

    while has_more and max_pages > 0:
        params = {
            "sec_user_id": sec_uid,
            "count": 21,
            "max_cursor": max_cursor,
            "aid": "6383",
            "device_platform": "webapp",
            "channel": "channel_pc_web",
        }
        try:
            r = requests.get(API_URL, params=params, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("API 请求失败（cursor=%d）：%s", max_cursor, e)
            break

        aweme_list = data.get("aweme_list") or []
        if not aweme_list:
            break

        for a in aweme_list:
            all_items.append(_aweme_to_item(a))

        has_more = data.get("has_more", 0) == 1
        max_cursor = data.get("max_cursor", 0)
        max_pages -= 1
        time.sleep(0.8)  # 限速避免风控

    # 去重
    seen = set()
    unique = []
    for it in all_items:
        aid = it.get("id")
        if aid and aid not in seen:
            seen.add(aid)
            unique.append(it)

    logger.info("HTTP 采集到 %d 条收藏（去重后）", len(unique))
    return unique


def _aweme_to_item(a: dict) -> dict:
    """解析抖音 API 返回的 aweme 结构。与 collector.py 保持一致。"""
    aweme_id = str(a.get("aweme_id") or "")
    author = a.get("author") or {}
    video = a.get("video") or {}
    cover_list = (video.get("cover", {}) or {}).get("url_list") or []
    play_list = (video.get("play_addr", {}) or {}).get("url_list") or []
    desc = (a.get("desc") or "").strip()
    title = desc.split("\n")[0].strip() or desc[:80]
    return {
        "id": aweme_id,
        "title": title[:80],
        "author": author.get("nickname", "") or "",
        "desc": desc,
        "url": f"https://www.douyin.com/video/{aweme_id}",
        "cover_url": cover_list[0] if cover_list else "",
        "play_url": play_list[0] if play_list else "",
        "duration": video.get("duration", 0),
        "create_time": a.get("create_time", 0),
    }


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _save_raw(items: list):
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def collect_http(cfg: dict) -> list:
    """采集入口：HTTP 方式拉取 → only_new 过滤 → 返回新增列表。"""
    items = _scrape_http(cfg)
    if not items:
        return []

    _save_raw(items)
    logger.info("采集到 %d 条", len(items))

    if not cfg["collection"].get("only_new", False):
        return items

    state = _load_state()
    seen = set(state.get("seen_ids") or [])
    if not seen:
        state["last_run"] = today_str()
        state["seen_ids"] = [it["id"] for it in items]
        _save_state(state)
        logger.info("首次运行：已将 %d 条收藏标记为基线", len(items))
        return []

    new_items = [it for it in items if it["id"] not in seen]
    state["last_run"] = today_str()
    state["seen_ids"] = [it["id"] for it in items]
    _save_state(state)
    logger.info("only_new：本次 %d 条中新增 %d 条", len(items), len(new_items))
    return new_items
