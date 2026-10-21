import asyncio
import logging
from datetime import datetime, timedelta
from db import (
    get_user, add_credits, deduct_credits, get_setting, set_setting,
    create_bomb, finish_bomb, conn,
)

log = logging.getLogger("credits")

COST_MAP = {
    "sms":      "bomb_cost_sms",
    "call":     "bomb_cost_call",
    "whatsapp": "bomb_cost_whatsapp",
    "all":      "bomb_cost_all",
}

_cooldown_locks: dict[int, asyncio.Lock] = {}


def _user_lock(uid: int) -> asyncio.Lock:
    if uid not in _cooldown_locks:
        _cooldown_locks[uid] = asyncio.Lock()
    return _cooldown_locks[uid]


async def _get_int(key: str, default: int) -> int:
    raw = await get_setting(key, str(default))
    try:
        v = int(raw)
        return v if v >= 0 else default
    except (TypeError, ValueError):
        log.warning("bad setting %s=%r, using %s", key, raw, default)
        return default


async def get_bomb_cost(category: str) -> int:
    key = COST_MAP.get(category, "bomb_cost_sms")
    return await _get_int(key, 1)


async def get_cooldown() -> int:
    return await _get_int("cooldown_seconds", 60)


async def get_free_credits() -> int:
    return await _get_int("free_credits", 5)


async def get_referral_credits() -> int:
    return await _get_int("referral_credits", 2)


async def check_cooldown(user: dict) -> tuple[bool, int]:
    if not user.get("last_bomb_at"):
        return True, 0
    try:
        last = datetime.fromisoformat(user["last_bomb_at"])
    except (ValueError, TypeError):
        return True, 0
    elapsed = (datetime.utcnow() - last).total_seconds()
    cd = await get_cooldown()
    if user.get("is_premium"):
        cd = cd // 2
    if elapsed >= cd:
        return True, 0
    return False, int(cd - elapsed)


async def can_bomb(user_id: int, category: str) -> tuple[bool, str, int]:
    user = await get_user(user_id)
    if not user:
        return False, "❌ User not found.", 0
    if user["is_banned"]:
        return False, "🚫 You are banned.", 0
    if not user["is_verified"]:
        return False, "🔒 Please verify first.", 0
    cost = await get_bomb_cost(category)
    if user["credits"] < cost:
        return False, f"❌ Need {cost} credits. You have {user['credits']}.", cost
    ok, remain = await check_cooldown(user)
    if not ok:
        return False, f"⏳ Wait {remain}s before next bomb.", cost
    return True, "ok", cost


async def start_bomb(user_id: int, phone: str, category: str,
                     duration: int, resend: bool) -> tuple[bool, str, dict]:
    lock = _user_lock(user_id)
    async with lock:
        ok, msg, cost = await can_bomb(user_id, category)
        if not ok:
            return False, msg, {}

        async with conn().execute(
            "SELECT credits FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row or row["credits"] < cost:
                return False, "❌ Insufficient credits.", {}

        deducted = await deduct_credits(user_id, cost)
        if not deducted:
            return False, "❌ Credit deduction failed.", {}

        try:
            bomb_id = await create_bomb(
                user_id=user_id,
                phone=phone,
                category=category,
                duration_sec=duration,
                resend_mode=1 if resend else 0,
                credits_spent=cost,
            )
        except Exception as e:
            log.exception("create_bomb failed, refunding")
            await add_credits(user_id, cost)
            return False, f"❌ Bomb failed to start: {e}", {}

        log.info("bomb %s started user=%s target=%s cat=%s cost=%s",
                 bomb_id, user_id, phone, category, cost)
        return True, "started", {
            "bomb_id": bomb_id,
            "cost": cost,
            "category": category,
            "duration": duration,
            "resend": resend,
        }


async def end_bomb(bomb_id: int, hits: int, resends: int,
                   crashed: bool = False) -> None:
    try:
        await finish_bomb(bomb_id, hits, resends)
        log.info("bomb %s ended hits=%s resends=%s", bomb_id, hits, resends)
    except Exception:
        log.exception("finish_bomb failed id=%s", bomb_id)


async def refund_bomb(bomb_id: int, pct: float = 0.5) -> int:
    try:
        async with conn().execute(
            "SELECT user_id, credits_spent FROM bombs WHERE id=?",
            (bomb_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return 0
            refund = int(row["credits_spent"] * pct)
            if refund > 0:
                await add_credits(row["user_id"], refund)
            return refund
    except Exception:
        log.exception("refund failed id=%s", bomb_id)
        return 0


async def grant_referral(referrer_id: int) -> int:
    amt = await get_referral_credits()
    if amt <= 0:
        return 0
    return await add_credits(referrer_id, amt)


async def grant_free_credits(user_id: int) -> int:
    amt = await get_free_credits()
    if amt <= 0:
        return 0
    return await add_credits(user_id, amt)


async def get_balance(user_id: int) -> int:
    user = await get_user(user_id)
    return user["credits"] if user else 0


async def cleanup_cooldown_locks(max_idle: int = 3600) -> int:
    if len(_cooldown_locks) < 1000:
        return 0
    removed = 0
    for uid in list(_cooldown_locks.keys()):
        if not _cooldown_locks[uid].locked():
            del _cooldown_locks[uid]
            removed += 1
    return removed