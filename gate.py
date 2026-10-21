import asyncio
import logging
import time
from typing import Optional
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.enums import ChatMemberStatus

log = logging.getLogger("gate")


class ForceJoinMiddleware(BaseMiddleware):
    def __init__(self, channel_ids: list[int], channel_urls: list[str], owner_id: int = 0):
        super().__init__()
        self.channel_ids = channel_ids
        self.channel_urls = channel_urls
        self.owner_id = owner_id
        self._cache: dict[int, tuple[float, bool]] = {}
        self._cache_ttl = 300.0

    async def _is_member(self, bot, user_id: int) -> bool:
        now = time.time()
        cached = self._cache.get(user_id)
        if cached and (now - cached[0]) < self._cache_ttl:
            return cached[1]

        for ch_id in self.channel_ids:
            try:
                member = await bot.get_chat_member(ch_id, user_id)
                if member.status not in (
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.CREATOR,
                ):
                    self._cache[user_id] = (now, False)
                    return False
            except Exception as e:
                log.warning("chat_member check failed ch=%s uid=%s err=%s", ch_id, user_id, e)
                self._cache[user_id] = (now, False)
                return False

        self._cache[user_id] = (now, True)
        return True

    def _join_keyboard(self):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        kb = InlineKeyboardBuilder()
        for i, url in enumerate(self.channel_urls, start=1):
            kb.row(InlineKeyboardButton(text=f"📢 Join Channel {i}", url=url))
        kb.row(InlineKeyboardButton(text="✅ Verify", callback_data="gate_verify"))
        return kb.as_markup()

    def _join_text(self, failed: bool = False) -> str:
        if failed:
            return (
                "🔒 <b>Verification Failed</b>\n\n"
                "You haven't joined both channels yet.\n\n"
                "1️⃣ Join Channel 1\n"
                "2️⃣ Join Channel 2\n\n"
                "Then tap ✅ Verify again."
            )
        return (
            "🔒 <b>Verification Required</b>\n\n"
            "To use <b>CF — Prank Bomber</b>, join both channels:\n\n"
            "1️⃣ Main Channel\n"
            "2️⃣ Premium Channel\n\n"
            "After joining, tap <b>✅ Verify</b>."
        )

    async def __call__(self, handler, event: TelegramObject, data: dict):
        from db import get_user, set_verified
        from keyboards import main_menu_kb
        from texts import welcome_text

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            return await handler(event, data)

        if not user or user.is_bot:
            return

        bot = data["bot"]
        uid = user.id

        # Owner bypass — owner ko kabhi mat roko
        if self.owner_id and uid == self.owner_id:
            return await handler(event, data)

        # Verify button handler
        if isinstance(event, CallbackQuery) and event.data == "gate_verify":
            ok = await self._is_member(bot, uid)
            if ok:
                await set_verified(uid, True)
                self._cache[uid] = (time.time(), True)
                await event.answer("✅ Verified!")
                try:
                    await event.message.edit_text(
                        "✅ <b>Verification complete!</b>\n\n"
                        "Welcome to CF — Prank Bomber! 🖤"
                    )
                except Exception:
                    pass
                # Menu bhejo
                db_user = await get_user(uid)
                await event.message.answer(
                    welcome_text(db_user, event.from_user.first_name or "friend"),
                    reply_markup=main_menu_kb(),
                    parse_mode="HTML",
                )
            else:
                await event.answer("❌ Please join both channels first!", show_alert=True)
                try:
                    await event.message.edit_text(
                        self._join_text(failed=True),
                        reply_markup=self._join_keyboard(),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            return

        # Banned check
        db_user = await get_user(uid)
        if db_user and db_user.get("is_banned"):
            if isinstance(event, Message):
                await event.answer("🚫 You are banned from this bot.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 Banned.", show_alert=True)
            return

        # Already verified
        if db_user and db_user.get("is_verified"):
            return await handler(event, data)

        # Check membership
        ok = await self._is_member(bot, uid)
        if ok:
            await set_verified(uid, True)
            return await handler(event, data)

        # Not verified — show gate
        if isinstance(event, Message):
            await event.answer(
                self._join_text(),
                reply_markup=self._join_keyboard(),
                disable_web_page_preview=True,
                parse_mode="HTML",
            )
        elif isinstance(event, CallbackQuery):
            try:
                await event.message.edit_text(
                    self._join_text(),
                    reply_markup=self._join_keyboard(),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            except Exception:
                await event.message.answer(
                    self._join_text(),
                    reply_markup=self._join_keyboard(),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            await event.answer("Please verify first.")
        return


class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        from db import get_user

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        if not user or user.is_bot:
            return

        db_user = await get_user(user.id)
        if db_user and db_user.get("is_banned"):
            if isinstance(event, Message):
                await event.answer("🚫 You are banned.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 Banned.", show_alert=True)
            return

        return await handler(event, data)


class MaintenanceMiddleware(BaseMiddleware):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def __call__(self, handler, event: TelegramObject, data: dict):
        from db import get_setting

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        if not user or user.id == self.owner_id:
            return await handler(event, data)

        mode = await get_setting("maintenance", "0")
        if mode == "1":
            if isinstance(event, Message):
                await event.answer("🔧 Bot under maintenance. Try again later.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔧 Maintenance mode.", show_alert=True)
            return

        return await handler(event, data)