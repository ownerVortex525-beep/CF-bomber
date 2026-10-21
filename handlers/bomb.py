import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from db import get_user
from keyboards import (
    bomb_category_kb, bomb_duration_kb, bomb_resend_kb,
    bomb_confirm_kb, stop_kb, main_menu_kb, cancel_kb,
)
from texts import (
    bomb_category_text, bomb_duration_text,
    bomb_resend_text, bomb_confirm_text,
    bomb_progress_text, bomb_final_text,
)
from credits import start_bomb, end_bomb, can_bomb, get_balance
from bomber import run_bomb

log = logging.getLogger("handler.bomb")
router = Router(name="bomb")

PHONE_RE = re.compile(r"^(\+?91)?(\d{10})$")
active_bombs: dict[int, dict] = {}


def normalize_phone(raw: str):
    s = re.sub(r"[\s\-()]", "", raw.strip())
    m = PHONE_RE.match(s)
    if not m:
        return None
    return m.group(2)


@router.message(F.text, StateFilter("bomb:phone"))
async def step_phone(message: Message, state: FSMContext, **kwargs):
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer(
            "❌ Invalid number.\n"
            "Send <code>+91XXXXXXXXXX</code> or 10-digit number.",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return
    await state.update_data(phone=phone)
    await state.set_state("bomb:category")
    await message.answer(
        bomb_category_text(phone),
        parse_mode="HTML",
        reply_markup=bomb_category_kb(),
    )


@router.callback_query(F.data.startswith("cat:"), StateFilter("bomb:category"))
async def step_category(cb: CallbackQuery, state: FSMContext, **kwargs):
    cat = cb.data.split(":", 1)[1]
    if cat not in ("sms", "call", "whatsapp", "all"):
        await cb.answer("❌ Invalid category.")
        return
    user_id = cb.from_user.id
    ok, msg, cost = await can_bomb(user_id, cat)
    if not ok:
        await cb.answer(msg, show_alert=True)
        return
    await state.update_data(category=cat, cost=cost)
    await state.set_state("bomb:duration")
    try:
        await cb.message.edit_text(
            bomb_duration_text(cat, cost),
            parse_mode="HTML",
            reply_markup=bomb_duration_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("dur:"), StateFilter("bomb:duration"))
async def step_duration(cb: CallbackQuery, state: FSMContext, **kwargs):
    try:
        dur = int(cb.data.split(":", 1)[1])
    except ValueError:
        await cb.answer("❌ Invalid duration.")
        return
    if dur not in (15, 30, 60, 120):
        await cb.answer("❌ Invalid duration.")
        return
    await state.update_data(duration=dur)
    await state.set_state("bomb:resend")
    try:
        await cb.message.edit_text(
            bomb_resend_text(),
            parse_mode="HTML",
            reply_markup=bomb_resend_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("resend:"), StateFilter("bomb:resend"))
async def step_resend(cb: CallbackQuery, state: FSMContext, **kwargs):
    mode = cb.data.split(":", 1)[1]
    if mode not in ("on", "off"):
        await cb.answer("❌ Invalid.")
        return
    await state.update_data(resend=(mode == "on"))
    data = await state.get_data()
    await state.set_state("bomb:confirm")
    try:
        await cb.message.edit_text(
            bomb_confirm_text(
                data["phone"], data["category"],
                data["duration"], data["resend"], data["cost"],
            ),
            parse_mode="HTML",
            reply_markup=bomb_confirm_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "bomb:cancel", StateFilter("bomb:confirm"))
async def step_cancel(cb: CallbackQuery, state: FSMContext, **kwargs):
    await state.clear()
    await cb.answer("❌ Cancelled.")
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.message.answer("🏠 Main Menu", reply_markup=main_menu_kb(cb.from_user.id))


@router.callback_query(F.data == "bomb:go", StateFilter("bomb:confirm"))
async def step_go(cb: CallbackQuery, state: FSMContext, **kwargs):
    data = await state.get_data()
    await state.clear()

    user_id = cb.from_user.id
    phone = data["phone"]
    category = data["category"]
    duration = data["duration"]
    resend = data["resend"]

    if user_id in active_bombs:
        await cb.answer("⏳ Another bomb is already running.", show_alert=True)
        return

    ok, msg, info = await start_bomb(
        user_id=user_id,
        phone=phone,
        category=category,
        duration=duration,
        resend=resend,
    )
    if not ok:
        await cb.answer(msg, show_alert=True)
        return

    bomb_id = info["bomb_id"]
    active_bombs[user_id] = {"bomb_id": bomb_id, "stop": False}

    try:
        await cb.message.delete()
    except Exception:
        pass

    live_msg = await cb.message.answer(
        bomb_progress_text({
            "phone": phone, "category": category,
            "elapsed": 0, "remaining": duration,
            "hits": 0, "fails": 0, "resends": 0,
            "tick": 0, "apis_fired": 0,
        }),
        parse_mode="HTML",
        reply_markup=stop_kb(),
    )
    await cb.answer("💣 Bomb started!")

    last_edit = [0.0]

    async def progress_cb(p: dict):
        if active_bombs.get(user_id, {}).get("stop"):
            return
        now = asyncio.get_event_loop().time()
        if now - last_edit[0] < 3.0:
            return
        last_edit[0] = now
        try:
            await live_msg.edit_text(
                bomb_progress_text({
                    "phone": phone, "category": category,
                    "elapsed": p["elapsed"],
                    "remaining": p["remaining"],
                    "hits": p["hits"],
                    "fails": p["fails"],
                    "resends": p.get("resends", 0),
                    "tick": p["tick"],
                    "apis_fired": p["apis_fired"],
                }),
                parse_mode="HTML",
                reply_markup=stop_kb(),
            )
        except Exception:
            pass

    try:
        result = await run_bomb(
            bomb_id=bomb_id,
            user_id=user_id,
            phone=phone,
            category=category,
            duration_sec=duration,
            resend_mode=resend,
            progress_cb=progress_cb,
        )
    except Exception:
        log.exception("bomb run crashed")
        result = {"hits": 0, "fails": 0, "resends": 0, "duration": 0, "ticks": 0}

    active_bombs.pop(user_id, None)

    await end_bomb(bomb_id, result["hits"], result.get("resends", 0))

    balance = await get_balance(user_id)

    try:
        await live_msg.edit_text(
            bomb_final_text(
                phone, result["hits"],
                result.get("resends", 0),
                result["duration"], balance,
                result.get("ticks", 0),
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "bomb:stop")
async def step_stop(cb: CallbackQuery, **kwargs):
    user_id = cb.from_user.id
    entry = active_bombs.get(user_id)
    if not entry:
        await cb.answer("⚠️ No active bomb.", show_alert=True)
        return
    entry["stop"] = True
    await cb.answer("🛑 Stopping...")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.message(F.text == "🛑 STOP")
async def btn_stop(message: Message, **kwargs):
    user_id = message.from_user.id
    entry = active_bombs.get(user_id)
    if not entry:
        await message.answer("⚠️ No active bomb.")
        return
    entry["stop"] = True
    await message.answer("🛑 Stop signal sent. Bomb will end after current tick.")


@router.message(F.text, StateFilter("bomb:category"))
async def ignore_category_typing(message: Message, **kwargs):
    await message.answer("👇 Pick a category above.")


@router.message(F.text, StateFilter("bomb:duration"))
async def ignore_duration_typing(message: Message, **kwargs):
    await message.answer("👇 Pick a duration above.")


@router.message(F.text, StateFilter("bomb:resend"))
async def ignore_resend_typing(message: Message, **kwargs):
    await message.answer("👇 Pick resend mode above.")


@router.message(F.text, StateFilter("bomb:confirm"))
async def ignore_confirm_typing(message: Message, **kwargs):
    await message.answer("👇 Tap START or CANCEL.")