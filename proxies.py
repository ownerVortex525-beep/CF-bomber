import asyncio
import logging
import time
import random
from typing import Optional
import aiohttp
from db import (
    add_proxy, list_proxies, alive_proxies, update_proxy_status,
    mark_proxy_used, remove_dead_proxies, get_host_state,
    ban_host_direct, host_direct_banned,
)

log = logging.getLogger("proxies")

HEALTH_CHECK_URLS = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://ipinfo.io/json",
]

CHECK_TIMEOUT = 8
CHECK_INTERVAL = 1800
LOW_HEALTH_THRESHOLD = 20

_connector: Optional[aiohttp.TCPConnector] = None
_session: Optional[aiohttp.ClientSession] = None
OWNER_ID_FALLBACK: int = 0


async def init_proxy_engine() -> None:
    global _connector, _session
    _connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    _session = aiohttp.ClientSession(connector=_connector)
    log.info("proxy engine ready")


async def close_proxy_engine() -> None:
    global _session, _connector
    if _session:
        await _session.close()
        _session = None
    if _connector:
        await _connector.close()
        _connector = None


def _session_ref() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("proxy engine not initialized")
    return _session


def _build_proxy_url(proxy: dict) -> str:
    scheme = proxy["scheme"] or "http"
    if proxy.get("username") and proxy.get("password"):
        return f"{scheme}://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"
    return f"{scheme}://{proxy['host']}:{proxy['port']}"


async def check_proxy(proxy: dict) -> tuple[bool, int]:
    url = _build_proxy_url(proxy)
    start = time.time()
    for check in HEALTH_CHECK_URLS:
        try:
            async with _session_ref().get(
                check, proxy=url, timeout=aiohttp.ClientTimeout(total=CHECK_TIMEOUT),
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    latency = int((time.time() - start) * 1000)
                    return True, latency
        except Exception:
            continue
    return False, 0


async def verify_all_proxies() -> dict:
    proxies = await list_proxies()
    if not proxies:
        return {"alive": 0, "dead": 0, "total": 0}
    results = await asyncio.gather(
        *[check_proxy(p) for p in proxies], return_exceptions=True
    )
    alive = 0
    dead = 0
    for proxy, res in zip(proxies, results):
        if isinstance(res, Exception):
            await update_proxy_status(proxy["id"], False)
            dead += 1
            continue
        ok, latency = res
        await update_proxy_status(proxy["id"], ok, latency)
        if ok:
            alive += 1
        else:
            dead += 1
    log.info("proxy sweep alive=%s dead=%s", alive, dead)
    return {"alive": alive, "dead": dead, "total": len(proxies)}


async def verify_proxy_by_id(proxy_id: int) -> bool:
    proxies = await list_proxies()
    target = next((p for p in proxies if p["id"] == proxy_id), None)
    if not target:
        return False
    ok, latency = await check_proxy(target)
    await update_proxy_status(proxy_id, ok, latency)
    return ok


async def add_proxies_bulk(lines: list[str], admin_id: int) -> dict:
    added = 0
    failed = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ok = await add_proxy(line, admin_id)
        if ok:
            added += 1
        else:
            failed += 1
    log.info("proxy bulk add: +%s failed=%s", added, failed)
    return {"added": added, "failed": failed}


async def pick_proxy(host: str) -> Optional[str]:
    if await host_direct_banned(host):
        pool = await alive_proxies()
        if not pool:
            return None
        total_health = sum(p["health"] for p in pool)
        if total_health <= 0:
            chosen = random.choice(pool)
        else:
            r = random.uniform(0, total_health)
            chosen = pool[-1]
            acc = 0
            for p in pool:
                acc += p["health"]
                if r <= acc:
                    chosen = p
                    break
        await mark_proxy_used(chosen["id"])
        return _build_proxy_url(chosen)
    return None


async def report_success(host: str, proxy_url: Optional[str]) -> None:
    if proxy_url:
        proxies = await list_proxies()
        for p in proxies:
            if _build_proxy_url(p) == proxy_url:
                await update_proxy_status(p["id"], True)
                return


async def report_ban(host: str, proxy_url: Optional[str]) -> None:
    if proxy_url:
        proxies = await list_proxies()
        for p in proxies:
            if _build_proxy_url(p) == proxy_url:
                await update_proxy_status(p["id"], False)
                return
    else:
        await ban_host_direct(host, 300)


async def proxy_watchdog_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await verify_all_proxies()
            await remove_dead_proxies()
        except Exception:
            log.exception("proxy watchdog error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            continue


async def proxy_summary() -> dict:
    proxies = await list_proxies()
    alive = sum(1 for p in proxies if p["status"] == "alive")
    dead = sum(1 for p in proxies if p["status"] == "dead")
    unchecked = sum(1 for p in proxies if p["status"] == "unchecked")
    avg_health = sum(p["health"] for p in proxies) // max(len(proxies), 1)
    return {
        "total": len(proxies),
        "alive": alive,
        "dead": dead,
        "unchecked": unchecked,
        "avg_health": avg_health,
    }


async def clear_dead() -> int:
    return await remove_dead_proxies()


# ============================================================
# PROXY SCRAPER — auto-fetches free proxies from public pools
# ============================================================
SCRAPER_URLS = [
    "https://raw.githubusercontent.com/proxy-list-org/proxy-list/main/proxy.txt",
    "https://raw.githubusercontent.com/cljoly/proxy-list/master/proxy.txt",
    "https://raw.githubusercontent.com/midass-x/Proxy-Scrapper/main/SOCKS5.txt",
]

_imported = set()


def _normalize_proxy(line: str) -> Optional[str]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if ":" not in line:
        return None
    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{int(port)}"
    if len(parts) >= 4:
        host, port = parts[0], parts[1]
        user, pw = parts[2], parts[3]
        return f"http://{user}:{pw}@{host}:{int(port)}"
    return None


async def scrape_proxies(limit: int = 30, owner_id: int = 0) -> int:
    """Scrape free proxies from public pools. Returns count added."""
    global _imported
    if not _session:
        await init_proxy_engine()
    added = 0
    for url in SCRAPER_URLS:
        try:
            async with _session_ref().get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                text = await resp.text()
                for line in text.splitlines():
                    if added >= limit:
                        return added
                    normalized = _normalize_proxy(line)
                    if not normalized:
                        continue
                    if normalized in _imported:
                        continue
                    _imported.add(normalized)
                    if await add_proxy(normalized, owner_id):
                        added += 1
        except Exception:
            continue
    log.info("scraped +%s proxies (target was %s)", added, limit)
    return added


async def proxy_scraper_loop(stop_event: asyncio.Event, interval: int = 600) -> None:
    """Background loop: scrape + verify proxies periodically."""
    from config import OWNER_ID
    while not stop_event.is_set():
        try:
            await scrape_proxies(limit=20, owner_id=OWNER_ID)
        except Exception:
            log.exception("proxy scraper error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue