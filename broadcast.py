import asyncio
import logging
import time
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest
from db import all_user_ids, start_broadcast, update_broadcast

log = logging.getLogger("broadcast")

BATCH_SIZE = 25
SLEEP_BETWEEN = 0.05
PROGRESS_EVERY = 50


async def _send_one(bot: Bot, uid: int, kind: str, payload: dict) -> str:
    try:
        if kind == "text":
            await bot.send_message(uid, payload["text"], parse_mode=payload.get("parse_mode"))
        elif kind == "photo":
            await bot.send_photo(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
        elif kind == "video":
            await bot.send_video(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
        elif kind == "document":
            await bot.send_document(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
        else:
            return "fail"
        return "sent"
    except TelegramForbiddenError:
        return "blocked"
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            if kind == "text":
                await bot.send_message(uid, payload["text"], parse_mode=payload.get("parse_mode"))
            elif kind == "photo":
                await bot.send_photo(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
            elif kind == "video":
                await bot.send_video(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
            elif kind == "document":
                await bot.send_document(uid, payload["file_id"], caption=payload.get("caption"), parse_mode=payload.get("parse_mode"))
            return "sent"
        except Exception:
            return "fail"
    except TelegramBadRequest:
        return "fail"
    except Exception:
        return "fail"


async def broadcast(bot: Bot, admin_id: int, kind: str, payload: dict,
                    progress_cb=None, only_verified: bool = False) -> dict:
    bid = await start_broadcast(admin_id, kind)
    users = await all_user_ids(only_verified=only_verified)
    total = len(users)
    sent = 0
    fail = 0
    blocked = 0
    start = time.time()

    log.info("broadcast %s start admin=%s total=%s kind=%s", bid, admin_id, total, kind)

    for i in range(0, total, BATCH_SIZE):
        batch = users[i:i + BATCH_SIZE]
        results = await asyncio.gather(
            *[_send_one(bot, uid, kind, payload) for uid in batch],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                fail += 1
            elif r == "sent":
                sent += 1
            elif r == "blocked":
                blocked += 1
            else:
                fail += 1

        await asyncio.sleep(SLEEP_BETWEEN)

        done = sent + fail + blocked
        if progress_cb and (done % PROGRESS_EVERY == 0 or done == total):
            try:
                await progress_cb({
                    "total": total,
                    "done": done,
                    "sent": sent,
                    "fail": fail,
                    "blocked": blocked,
                    "elapsed": int(time.time() - start),
                })
            except Exception:
                pass

    await update_broadcast(bid, sent, fail, blocked, done=True)
    log.info("broadcast %s done sent=%s fail=%s blocked=%s dur=%ss",
             bid, sent, fail, blocked, int(time.time() - start))

    return {
        "id": bid,
        "total": total,
        "sent": sent,
        "fail": fail,
        "blocked": blocked,
        "duration": int(time.time() - start),
    }


def format_progress(p: dict) -> str:
    pct = int((p["done"] / max(p["total"], 1)) * 100)
    bar_len = 12
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        "📢 <b>BROADCAST</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"⏳ [{bar}] {pct}%\n"
        f"✅ Sent: <b>{p['sent']}</b>\n"
        f"❌ Fail: <b>{p['fail']}</b>\n"
        f"🚫 Blocked: <b>{p['blocked']}</b>\n"
        f"👥 Done: <b>{p['done']}</b> / {p['total']}\n"
        f"⏱️ Elapsed: {p['elapsed']}s"
    )


def format_final(r: dict) -> str:
    return (
        "✅ <b>BROADCAST COMPLETE</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 Total: <b>{r['total']}</b>\n"
        f"✅ Sent: <b>{r['sent']}</b>\n"
        f"❌ Failed: <b>{r['fail']}</b>\n"
        f"🚫 Blocked: <b>{r['blocked']}</b>\n"
        f"⏱️ Duration: {r['duration']}s"
    )