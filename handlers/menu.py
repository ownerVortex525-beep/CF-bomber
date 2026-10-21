import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from db import get_user
from keyboards import (
    main_menu_kb, bomb_category_kb, bomb_duration_kb,
    bomb_resend_kb, bomb_confirm_kb, cancel_kb,
)
from texts import (
    menu_text, balance_text, bomb_category_text,
    bomb_duration_text, bomb_resend_text, bomb_confirm_text,
)
from credits import get_bomb_cost, get_balance

log = logging.getLogger("handler.menu")
router = Router(name="menu")


@router.message(F.text == "💣 START BOMB")
async def btn_start_bomb(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user or not user.get("is_verified"):
        await message.answer("🔒 Please verify first.")
        return
    await state.set_state("bomb:phone")
    await message.answer(
        "🎯 <b>Send target number</b>\n\n"
        "Format:\n"
        "• <code>+91XXXXXXXXXX</code>\n"
        "• <code>10-digit number</code>\n\n"
        "Send /cancel to abort.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(F.text == "💰 BALANCE")
async def btn_balance(message: Message, **kwargs):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("❌ User not found. /start again.")
        return
    await message.answer(balance_text(user), parse_mode="HTML")


@router.message(Command("balance"))
async def cmd_balance(message: Message, **kwargs):
    await btn_balance(message)


@router.message(F.text == "👥 REFERRAL")
async def btn_referral(message: Message, **kwargs):
    from texts import referral_text
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("❌ User not found.")
        return
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    await message.answer(
        referral_text(user, link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("referral"))
async def cmd_referral(message: Message, **kwargs):
    await btn_referral(message)


@router.message(F.text == "🎟️ REDEEM")
async def btn_redeem(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    await state.set_state("redeem:code")
    await message.answer(
        "🎟️ <b>Send your redeem code</b>\n\n"
        "Example: <code>CF-XXXX-XXXX</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(Command("redeem"))
async def cmd_redeem(message: Message, state: FSMContext, **kwargs):
    await btn_redeem(message, state)


@router.message(F.text == "ℹ️ ABOUT")
async def btn_about(message: Message, **kwargs):
    await message.answer(
        "💣 <b>CF — PRANK BOMBER</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🖤 Fast · Clean · Limitless\n\n"
        "<b>Features</b>\n"
        "⚡ 100+ live APIs\n"
        "📩 SMS · 📞 Call · 📱 WhatsApp · 🔥 ALL\n"
        "💎 Credit system + referrals\n"
        "🎟️ Redeem codes\n"
        "🔒 Verified users only\n\n"
        "⚠️ <b>Use at your own risk.</b>\n"
        "🎯 <b>For prank use with friends only.</b>\n"
        "🛡️ We are not responsible for misuse.",
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    user = await get_user(message.from_user.id)
    await message.answer(
        "❌ Cancelled.",
        reply_markup=main_menu_kb(message.from_user.id) if user else None,
    )


@router.message(F.text == "❌ CANCEL")
async def btn_cancel(message: Message, state: FSMContext, **kwargs):
    await cmd_cancel(message, state)


@router.callback_query(F.data == "menu:back")
async def cb_menu_back(cb: CallbackQuery, state: FSMContext, **kwargs):
    await state.clear()
    user = await get_user(cb.from_user.id)
    if user:
        await cb.message.edit_text(menu_text(user), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(cb: CallbackQuery, state: FSMContext, **kwargs):
    await state.clear()
    user = await get_user(cb.from_user.id)
    if user:
        await cb.message.delete()
        await cb.message.answer(
            "🏠 <b>Main Menu</b>",
            reply_markup=main_menu_kb(cb.from_user.id),
            parse_mode="HTML",
        )
    await cb.answer()