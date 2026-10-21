from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from config import CHANNEL_URLS, OWNER_ID


def main_menu_kb(user_id: int | None = None) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="💣 START BOMB"))
    kb.row(
        KeyboardButton(text="💰 BALANCE"),
        KeyboardButton(text="👥 REFERRAL"),
    )
    kb.row(
        KeyboardButton(text="🎟️ REDEEM"),
        KeyboardButton(text="ℹ️ ABOUT"),
    )
    kb.row(
        KeyboardButton(text="🆘 HELP"),
        KeyboardButton(text="🛑 STOP"),
    )
    if user_id and user_id == OWNER_ID:
        kb.row(KeyboardButton(text="🛡 ADMIN"))
    return kb.as_markup(resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="❌ CANCEL"))
    return kb.as_markup(resize_keyboard=True)


def gate_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, url in enumerate(CHANNEL_URLS, start=1):
        kb.row(KeyboardButton(text=f"📢 Join Channel {i}") if False else None) if False else None
        from aiogram.types import InlineKeyboardButton
        kb.row(InlineKeyboardButton(text=f"📢 Join Channel {i}", url=url))
    from aiogram.types import InlineKeyboardButton
    kb.row(InlineKeyboardButton(text="✅ Verify", callback_data="gate_verify"))
    return kb.as_markup()


def bomb_category_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        __ibtn("📩 SMS · 1cr", "cat:sms"),
        __ibtn("📞 CALL · 2cr", "cat:call"),
    )
    kb.row(
        __ibtn("📱 WHATSAPP · 2cr", "cat:whatsapp"),
        __ibtn("🔥 ALL · 3cr", "cat:all"),
    )
    kb.row(__ibtn("❌ Cancel", "menu:main"))
    return kb.as_markup()


def bomb_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        __ibtn("⏱ 15s", "dur:15"),
        __ibtn("⏱ 30s", "dur:30"),
    )
    kb.row(
        __ibtn("⏱ 60s", "dur:60"),
        __ibtn("⏱ 120s", "dur:120"),
    )
    kb.row(__ibtn("⬅️ Back", "menu:main"))
    return kb.as_markup()


def bomb_resend_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        __ibtn("🔁 Resend ON", "resend:on"),
        __ibtn("➡️ Resend OFF", "resend:off"),
    )
    kb.row(__ibtn("⬅️ Back", "menu:main"))
    return kb.as_markup()


def bomb_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        __ibtn("▶️ START", "bomb:go"),
        __ibtn("❌ CANCEL", "bomb:cancel"),
    )
    return kb.as_markup()


def stop_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(__ibtn("🛑 STOP", "bomb:stop"))
    return kb.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(__ibtn("📢 Broadcast", "admin:broadcast"))
    kb.row(
        __ibtn("🎟️ Codes", "admin:codes"),
        __ibtn("🔌 Proxies", "admin:proxies"),
    )
    kb.row(
        __ibtn("👤 Users", "admin:users"),
        __ibtn("⚙️ Settings", "admin:settings"),
    )
    kb.row(__ibtn("📊 Stats", "admin:stats"))
    return kb.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(__ibtn("⬅️ Back", "admin:back"))
    return kb.as_markup()


def __ibtn(text: str, data: str):
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text=text, callback_data=data)