import asyncio
import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional
from db import (
    create_code, get_code, redeem_code, revoke_code,
    list_codes, cleanup_expired_codes, code_stats,
)

log = logging.getLogger("redeem")

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_PREFIX = "CF"
CODE_BODY_LEN = 8


def _gen_body() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_BODY_LEN))


def _format(body: str) -> str:
    return f"{CODE_PREFIX}-{body[:4]}-{body[4:]}"


async def generate_unique_code(max_tries: int = 10) -> str:
    for _ in range(max_tries):
        code = _format(_gen_body())
        existing = await get_code(code)
        if not existing:
            return code
    raise RuntimeError("code collision after max_tries")


async def create_redeem_code(
    credits: int,
    max_uses: int,
    expires_in_hours: Optional[int],
    note: Optional[str],
    created_by: int,
) -> str:
    if credits <= 0:
        raise ValueError("credits must be > 0")
    if max_uses <= 0:
        raise ValueError("max_uses must be > 0")
    expires_at = None
    if expires_in_hours and expires_in_hours > 0:
        expires_at = (datetime.utcnow() + timedelta(hours=expires_in_hours)).isoformat()
    code = await generate_unique_code()
    await create_code(
        code=code,
        credits=credits,
        max_uses=max_uses,
        expires_at=expires_at,
        note=note,
        created_by=created_by,
    )
    log.info("code created %s credits=%s max_uses=%s by=%s",
             code, credits, max_uses, created_by)
    return code


async def create_bulk_codes(
    count: int,
    credits: int,
    max_uses: int,
    expires_in_hours: Optional[int],
    note: Optional[str],
    created_by: int,
) -> list[str]:
    if count <= 0 or count > 500:
        raise ValueError("count must be 1..500")
    codes: list[str] = []
    for _ in range(count):
        codes.append(await create_redeem_code(
            credits=credits,
            max_uses=max_uses,
            expires_in_hours=expires_in_hours,
            note=note,
            created_by=created_by,
        ))
    return codes


async def redeem(user_id: int, raw_code: str) -> tuple[bool, str, int]:
    code = raw_code.strip().upper()
    if not code:
        return False, "❌ Empty code.", 0
    ok, msg, amount = await redeem_code(code, user_id)
    if ok:
        log.info("redeem user=%s code=%s credits=%s", user_id, code, amount)
    else:
        log.warning("redeem fail user=%s code=%s reason=%s", user_id, code, msg)
    return ok, msg, amount


async def revoke(raw_code: str) -> bool:
    code = raw_code.strip().upper()
    ok = await revoke_code(code)
    if ok:
        log.info("code revoked %s", code)
    return ok


async def purge_expired(days: int = 7) -> int:
    n = await cleanup_expired_codes(days)
    return n


async def stats() -> dict:
    return await code_stats()


async def active_codes(limit: int = 50) -> list[dict]:
    all_codes = await list_codes()
    now = datetime.utcnow().isoformat()
    active = []
    for c in all_codes:
        if c["is_revoked"]:
            continue
        if c["used_count"] >= c["max_uses"]:
            continue
        if c["expires_at"] and c["expires_at"] < now:
            continue
        active.append(c)
        if len(active) >= limit:
            break
    return active


async def cleanup_loop(stop_event: asyncio.Event, interval_hours: int = 6) -> None:
    interval = interval_hours * 3600
    while not stop_event.is_set():
        try:
            await purge_expired()
        except Exception:
            log.exception("cleanup loop error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def parse_duration(text: str) -> Optional[int]:
    """Parse '24h','7d','30d','never' → hours."""
    t = text.strip().lower()
    if t in ("never", "0", "none", "-"):
        return None
    if t.endswith("h"):
        try:
            return int(t[:-1])
        except ValueError:
            return None
    if t.endswith("d"):
        try:
            return int(t[:-1]) * 24
        except ValueError:
            return None
    try:
        return int(t)
    except ValueError:
        return None