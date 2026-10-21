import logging
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from db import get_user, conn
from keyboards import main_menu_kb, cancel_kb
from texts import referral_text, redeem_prompt_text, redeem_result_text
from redeem import redeem

log = logging.getLogger("handler.referral_redeem")
router = Router(name="referral_redeem")


@router.message(F.text == "👥 REFERRAL")
async def btn_referral(message: Message, **kwargs):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("❌ User not found. /start again.")
        return
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    async with conn().execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=?",
        (user["user_id"],),
    ) as cur:
        row = await cur.fetchone()
        count = row["c"] if row else 0
    await message.answer(
        referral_text(user, link, count),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(F.text == "🎟️ REDEEM")
async def btn_redeem(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    await state.set_state("redeem:code")
    await message.answer(
        redeem_prompt_text(),
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(F.text, StateFilter("redeem:code"))
async def step_code(message: Message, state: FSMContext, **kwargs):
    raw = (message.text or "").strip()
    if raw in ("❌ CANCEL", "/cancel"):
        await state.clear()
        user = await get_user(message.from_user.id)
        await message.answer(
            "❌ Cancelled.",
            reply_markup=main_menu_kb(message.from_user.id) if user else None,
        )
        return

    if not raw:
        await message.answer("❌ Empty code. Try again.", reply_markup=cancel_kb())
        return

    ok, msg, credits = await redeem(message.from_user.id, raw)

    await state.clear()
    user = await get_user(message.from_user.id)
    balance = user["credits"] if user else 0

    await message.answer(
        redeem_result_text(ok, msg, credits, balance),
        parse_mode="HTML",
        reply_markup=main_menu_kb(message.from_user.id) if user else None,
    )

    if ok:
        log.info("user %s redeemed code, +%s credits", message.from_user.id, credits)