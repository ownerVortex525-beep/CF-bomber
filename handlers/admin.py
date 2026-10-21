import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from config import OWNER_ID
from db import (
    get_user, set_banned, set_premium, add_credits, all_user_ids,
    total_users, list_proxies, reset_api_health, get_setting, set_setting,
    list_codes,
)
from keyboards import admin_kb, admin_back_kb, cancel_kb
from texts import admin_panel_text
from broadcast import broadcast, format_progress, format_final
from redeem import (
    create_redeem_code, create_bulk_codes, revoke,
    stats as code_stats, active_codes, parse_duration,
)
import proxies
from bomber import api_report

log = logging.getLogger("handler.admin")
router = Router(name="admin")


def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message, **kwargs):
    if not is_owner(message.from_user.id):
        return
    stats = {
        "users": await total_users(),
        "apis": await api_report(),
        "proxies": await proxies.proxy_summary(),
        "codes": await code_stats(),
    }
    await message.answer(
        admin_panel_text(stats),
        parse_mode="HTML",
        reply_markup=admin_kb(),
    )


@router.callback_query(F.data == "admin:back")
async def cb_admin_back(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.clear()
    stats = {
        "users": await total_users(),
        "apis": await api_report(),
        "proxies": await proxies.proxy_summary(),
        "codes": await code_stats(),
    }
    try:
        await cb.message.edit_text(
            admin_panel_text(stats),
            parse_mode="HTML",
            reply_markup=admin_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.clear()
    await state.set_state("admin:broadcast:text")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "📢 <b>Broadcast</b>\n\n"
            "Send the message to broadcast.\n"
            "Supports: text, photo, video, document.\n\n"
            "Use <code>{name}</code> for user first name.\n"
            "Add <code>#verified</code> at the top to send to verified only.",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:broadcast:text")
async def step_broadcast_send(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Cancelled.")
        return

    only_verified = False
    text = message.text or message.caption or ""
    if text.strip().startswith("#verified"):
        only_verified = True
        text = text.replace("#verified", "", 1).strip()

    kind = "text"
    payload = {"text": text, "parse_mode": "HTML"}
    if message.photo:
        kind = "photo"
        payload = {
            "file_id": message.photo[-1].file_id,
            "caption": text,
            "parse_mode": "HTML",
        }
    elif message.video:
        kind = "video"
        payload = {
            "file_id": message.video.file_id,
            "caption": text,
            "parse_mode": "HTML",
        }
    elif message.document:
        kind = "document"
        payload = {
            "file_id": message.document.file_id,
            "caption": text,
            "parse_mode": "HTML",
        }

    status_msg = await message.answer("📢 Broadcasting...")
    await state.clear()

    async def progress_cb(p):
        try:
            await status_msg.edit_text(format_progress(p), parse_mode="HTML")
        except Exception:
            pass

    result = await broadcast(
        bot=message.bot,
        admin_id=message.from_user.id,
        kind=kind,
        payload=payload,
        progress_cb=progress_cb,
        only_verified=only_verified,
    )
    try:
        await status_msg.edit_text(format_final(result), parse_mode="HTML")
    except Exception:
        await message.answer(format_final(result), parse_mode="HTML")


@router.callback_query(F.data == "admin:codes")
async def cb_admin_codes(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    s = await code_stats()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Create", callback_data="admin:code_create"))
    kb.row(InlineKeyboardButton(text="📋 Bulk Create", callback_data="admin:code_bulk"))
    kb.row(InlineKeyboardButton(text="📊 List Active", callback_data="admin:code_list"))
    kb.row(InlineKeyboardButton(text="📈 Stats", callback_data="admin:code_stats"))
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            f"🎟️ <b>Redeem Codes</b>\n\n"
            f"Total codes: {s.get('total', 0)}\n"
            f"Exhausted: {s.get('exhausted', 0)}\n"
            f"Redeems: {s.get('used', 0)}\n"
            f"Credits given: {s.get('credits_redeemed', 0)}",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:code_stats")
async def cb_code_stats(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    s = await code_stats()
    await cb.answer(
        f"Total: {s.get('total', 0)} · "
        f"Used: {s.get('used', 0)} · "
        f"Credits: {s.get('credits_redeemed', 0)}",
        show_alert=True,
    )


@router.callback_query(F.data == "admin:code_create")
async def cb_code_create(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.set_state("admin:code:params")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "🎟️ <b>Create Code</b>\n\n"
            "Send in format:\n"
            "<code>credits | max_uses | expiry | note</code>\n\n"
            "Example: <code>10 | 5 | 7d | welcome bonus</code>\n"
            "Expiry: <code>24h</code>, <code>7d</code>, <code>30d</code>, or <code>never</code>",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:code:params")
async def step_code_params(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    try:
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) < 3:
            raise ValueError("need credits | max_uses | expiry")
        credits = int(parts[0])
        max_uses = int(parts[1])
        hours = parse_duration(parts[2])
        note = parts[3] if len(parts) > 3 else None
    except Exception as e:
        await message.answer(f"❌ Invalid format: {e}")
        return

    code = await create_redeem_code(
        credits=credits,
        max_uses=max_uses,
        expires_in_hours=hours,
        note=note,
        created_by=message.from_user.id,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Code created</b>\n\n"
        f"<code>{code}</code>\n\n"
        f"💎 Credits: {credits}\n"
        f"👥 Max uses: {max_uses}\n"
        f"⏰ Expiry: {hours}h" if hours else "⏰ Expiry: never",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:code_bulk")
async def cb_code_bulk(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.set_state("admin:code:bulk")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "🎟️ <b>Bulk Create</b>\n\n"
            "Send: <code>count | credits | max_uses | expiry | note</code>\n\n"
            "Example: <code>10 | 5 | 1 | 7d | promo</code>",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:code:bulk")
async def step_code_bulk(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    try:
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) < 4:
            raise ValueError("need count | credits | max_uses | expiry")
        count = int(parts[0])
        credits = int(parts[1])
        max_uses = int(parts[2])
        hours = parse_duration(parts[3])
        note = parts[4] if len(parts) > 4 else None
    except Exception as e:
        await message.answer(f"❌ Invalid: {e}")
        return

    codes = await create_bulk_codes(
        count=count, credits=credits, max_uses=max_uses,
        expires_in_hours=hours, note=note,
        created_by=message.from_user.id,
    )
    await state.clear()

    text = "\n".join(codes)
    from io import BytesIO
    buf = BytesIO(text.encode())
    buf.name = "codes.txt"
    await message.answer_document(buf, caption=f"✅ {len(codes)} codes created")


@router.callback_query(F.data == "admin:code_list")
async def cb_code_list(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    codes = await active_codes(limit=30)
    if not codes:
        await cb.answer("No active codes.", show_alert=True)
        return
    lines = []
    for c in codes:
        exp = c["expires_at"][:10] if c["expires_at"] else "never"
        lines.append(
            f"<code>{c['code']}</code> · {c['credits']}cr · "
            f"{c['used_count']}/{c['max_uses']} · {exp}"
        )
    try:
        await cb.message.edit_text(
            "🎟️ <b>Active Codes</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
            reply_markup=admin_back_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:proxies")
async def cb_admin_proxies(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    s = await proxies.proxy_summary()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Add", callback_data="admin:proxy_add"))
    kb.row(InlineKeyboardButton(text="🔄 Test All", callback_data="admin:proxy_test"))
    kb.row(InlineKeyboardButton(text="📋 List", callback_data="admin:proxy_list"))
    kb.row(InlineKeyboardButton(text="🗑️ Clear Dead", callback_data="admin:proxy_clear"))
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            f"🔌 <b>Proxy Manager</b>\n\n"
            f"Total: {s['total']}\n"
            f"Alive: {s['alive']}\n"
            f"Dead: {s['dead']}\n"
            f"Unchecked: {s['unchecked']}\n"
            f"Avg health: {s['avg_health']}",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:proxy_add")
async def cb_proxy_add(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.set_state("admin:proxy:add")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "🔌 <b>Add Proxies</b>\n\n"
            "Send one per line. Formats:\n"
            "<code>http://user:pass@ip:port</code>\n"
            "<code>socks5://ip:port</code>\n"
            "<code>ip:port</code>\n"
            "<code>ip:port:user:pass</code>",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:proxy:add")
async def step_proxy_add(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    lines = (message.text or "").splitlines()
    res = await proxies.add_proxies_bulk(lines, message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Added: {res['added']}\n❌ Failed: {res['failed']}",
        reply_markup=admin_back_kb(),
    )


@router.callback_query(F.data == "admin:proxy_test")
async def cb_proxy_test(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await cb.answer("🔄 Testing all proxies...")
    res = await proxies.verify_all_proxies()
    try:
        await cb.message.edit_text(
            f"🔌 <b>Proxy Sweep Complete</b>\n\n"
            f"✅ Alive: {res['alive']}\n"
            f"❌ Dead: {res['dead']}\n"
            f"📊 Total: {res['total']}",
            parse_mode="HTML",
            reply_markup=admin_back_kb(),
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin:proxy_list")
async def cb_proxy_list(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    ps = await list_proxies()
    if not ps:
        await cb.answer("No proxies.", show_alert=True)
        return
    lines = []
    for p in ps[:20]:
        lines.append(
            f"<code>{p['host']}:{p['port']}</code> · "
            f"{p['status']} · h={p['health']}"
        )
    try:
        await cb.message.edit_text(
            "🔌 <b>Proxies</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
            reply_markup=admin_back_kb(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:proxy_clear")
async def cb_proxy_clear(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    n = await proxies.clear_dead()
    await cb.answer(f"🗑️ Removed {n} dead proxies", show_alert=True)


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await state.set_state("admin:user:target")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "👤 <b>User Lookup</b>\n\n"
            "Send user ID:",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:user:target")
async def step_user_target(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid user ID.")
        return
    u = await get_user(uid)
    if not u:
        await message.answer("❌ User not found.")
        await state.clear()
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"{'✅ Unban' if u['is_banned'] else '🚫 Ban'}",
        callback_data=f"admin:user:ban:{uid}",
    ))
    kb.row(InlineKeyboardButton(
        text=f"{'❌ Remove Premium' if u['is_premium'] else '⭐ Premium'}",
        callback_data=f"admin:user:prem:{uid}",
    ))
    kb.row(InlineKeyboardButton(
        text="💎 Add Credits",
        callback_data=f"admin:user:credit:{uid}",
    ))
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back"))
    await message.answer(
        f"👤 <b>User Info</b>\n\n"
        f"ID: <code>{u['user_id']}</code>\n"
        f"Username: @{u['username'] or 'none'}\n"
        f"Name: {u['first_name'] or 'unknown'}\n"
        f"💎 Credits: {u['credits']}\n"
        f"✅ Verified: {'yes' if u['is_verified'] else 'no'}\n"
        f"⭐ Premium: {'yes' if u['is_premium'] else 'no'}\n"
        f"🚫 Banned: {'yes' if u['is_banned'] else 'no'}\n"
        f"💣 Bombs: {u['total_bombs']}\n"
        f"💥 Hits: {u['total_hits']}",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:user:ban:"))
async def cb_user_ban(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[-1])
    u = await get_user(uid)
    if not u:
        await cb.answer("User not found.")
        return
    await set_banned(uid, not u["is_banned"])
    await cb.answer("✅ Updated")
    await step_user_target_edit(cb, uid)


@router.callback_query(F.data.startswith("admin:user:prem:"))
async def cb_user_prem(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[-1])
    u = await get_user(uid)
    if not u:
        await cb.answer("User not found.")
        return
    await set_premium(uid, not u["is_premium"])
    await cb.answer("✅ Updated")
    await step_user_target_edit(cb, uid)


@router.callback_query(F.data.startswith("admin:user:credit:"))
async def cb_user_credit(cb: CallbackQuery, state: FSMContext, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[-1])
    await state.update_data(target_user=uid)
    await state.set_state("admin:user:credit_amount")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            f"💎 <b>Add Credits to {uid}</b>\n\n"
            "Send amount (negative to remove):",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.message(state="admin:user:credit_amount")
async def step_user_credit_amount(message: Message, state: FSMContext, **kwargs):
    if not is_owner(message.from_user.id):
        return
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid amount.")
        return
    data = await state.get_data()
    uid = data.get("target_user")
    await state.clear()
    if not uid:
        return
    new_bal = await add_credits(uid, amount)
    await message.answer(
        f"✅ Added {amount} credits to {uid}\n"
        f"New balance: {new_bal}",
        reply_markup=admin_back_kb(),
    )


async def step_user_target_edit(cb: CallbackQuery, uid: int):
    u = await get_user(uid)
    if not u:
        return
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"{'✅ Unban' if u['is_banned'] else '🚫 Ban'}",
        callback_data=f"admin:user:ban:{uid}",
    ))
    kb.row(InlineKeyboardButton(
        text=f"{'❌ Remove Premium' if u['is_premium'] else '⭐ Premium'}",
        callback_data=f"admin:user:prem:{uid}",
    ))
    kb.row(InlineKeyboardButton(
        text="💎 Add Credits",
        callback_data=f"admin:user:credit:{uid}",
    ))
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            f"👤 <b>User Info</b>\n\n"
            f"ID: <code>{u['user_id']}</code>\n"
            f"💎 Credits: {u['credits']}\n"
            f"✅ Verified: {'yes' if u['is_verified'] else 'no'}\n"
            f"⭐ Premium: {'yes' if u['is_premium'] else 'no'}\n"
            f"🚫 Banned: {'yes' if u['is_banned'] else 'no'}",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin:settings")
async def cb_admin_settings(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    maint = await get_setting("maintenance", "0")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"🔧 Maintenance: {'ON' if maint == '1' else 'OFF'}",
        callback_data="admin:toggle_maint",
    ))
    kb.row(InlineKeyboardButton(text="🔄 Reset API Health", callback_data="admin:reset_apis"))
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back"))
    try:
        await cb.message.edit_text(
            "⚙️ <b>Settings</b>",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "admin:toggle_maint")
async def cb_toggle_maint(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    cur = await get_setting("maintenance", "0")
    new = "0" if cur == "1" else "1"
    await set_setting("maintenance", new)
    await cb.answer(f"Maintenance {'ON' if new == '1' else 'OFF'}")
    await cb_admin_settings(cb)


@router.callback_query(F.data == "admin:reset_apis")
async def cb_reset_apis(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    await reset_api_health()
    await cb.answer("✅ All API health reset to 100", show_alert=True)


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(cb: CallbackQuery, **kwargs):
    if not is_owner(cb.from_user.id):
        return
    stats = {
        "users": await total_users(),
        "apis": await api_report(),
        "proxies": await proxies.proxy_summary(),
        "codes": await code_stats(),
    }
    await cb.answer(
        f"👥 Users: {stats['users']}\n"
        f"🔌 Healthy APIs: {stats['apis']['healthy']}/{stats['apis']['total']}\n"
        f"🌐 Proxies alive: {stats['proxies']['alive']}\n"
        f"🎟️ Codes: {stats['codes'].get('total', 0)}",
        show_alert=True,
    )