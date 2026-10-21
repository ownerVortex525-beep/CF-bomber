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