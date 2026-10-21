import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from db import get_user, create_user, set_verified
from config import OWNER_ID
from keyboards import main_menu_kb, gate_kb
from texts import welcome_text, join_required_text
from credits import get_free_credits

log = logging.getLogger("handler.start")
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    uid = message.from_user.id
    user = await get_user(uid)

    if not user:
        referred_by = None
        args = message.text.split(maxsplit=1)
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_id = int(args[1][4:])
                if ref_id != uid:
                    ref_user = await get_user(ref_id)
                    if ref_user and not ref_user.get("is_banned"):
                        referred_by = ref_id
            except (ValueError, TypeError):
                pass

        free = await get_free_credits()
        user = await create_user(
            user_id=uid,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            referred_by=referred_by,
            free_credits=free,
        )
        log.info("new user %s referred_by=%s", uid, referred_by)

    if user.get("is_banned"):
        await message.answer("🚫 You are banned from this bot.")
        return

    # Owner ko hamesha verified rakho — warna owner bhi gate pe atak jata tha
    if uid == OWNER_ID and not user.get("is_verified"):
        await set_verified(uid, True)
        user = await get_user(uid) or {**user, "is_verified": 1}

    if not user.get("is_verified"):
        await message.answer(join_required_text(), reply_markup=gate_kb())
        return

    await message.answer(
        welcome_text(user, message.from_user.first_name or "friend"),
        reply_markup=main_menu_kb(uid),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, **kwargs):
    await message.answer(
        "💣 <b>CF — PRANK BOMBER · HELP</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "<b>Commands</b>\n"
        "/start — main menu\n"
        "/bomb — start a bomb\n"
        "/balance — check credits\n"
        "/referral — referral link\n"
        "/redeem — redeem a code\n"
        "/stop — stop active bomb\n"
        "/help — this message\n\n"
        "<b>Categories</b>\n"
        "📩 SMS · 📞 Call · 📱 WhatsApp · 🔥 ALL\n\n"
        "<b>Costs</b>\n"
        "SMS = 1 cr · Call = 2 cr · WhatsApp = 2 cr · ALL = 3 cr\n\n"
        "⚠️ <b>Use at your own risk.</b>\n"
        "🖤 For prank use with friends only.",
        parse_mode="HTML",
    )


@router.message(Command("verify"))
async def cmd_verify(message: Message, **kwargs):
    uid = message.from_user.id
    user = await get_user(uid)
    if uid == OWNER_ID:
        if user and not user.get("is_verified"):
            await set_verified(uid, True)
            user = await get_user(uid) or user
        if not user:
            await message.answer("Send /start first.")
            return
        await message.answer(
            welcome_text(user, message.from_user.first_name or "friend"),
            reply_markup=main_menu_kb(uid),
        )
        return
    if user and user.get("is_verified"):
        await message.answer("✅ You are already verified.")
        return
    await message.answer(join_required_text(), reply_markup=gate_kb())


@router.message(F.text == "🆘 HELP")
async def btn_help(message: Message, **kwargs):
    await cmd_help(message)


@router.message(F.text == "⬅️ BACK")
async def btn_back(message: Message, state: FSMContext, **kwargs):
    await state.clear()
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(
            welcome_text(user, message.from_user.first_name or "friend"),
            reply_markup=main_menu_kb(message.from_user.id),
        )
