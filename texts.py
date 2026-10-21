def welcome_text(user: dict, name: str) -> str:
    return (
        "╔══════════════════════╗\n"
        "║   💣 <b>CF — PRANK BOMBER</b>   ║\n"
        "╚══════════════════════╝\n\n"
        f"🖤 Welcome, <b>{name}</b>\n"
        f"💎 Credits: <b>{user.get('credits', 0)}</b>\n"
        f"✅ Status: <b>{'VERIFIED' if user.get('is_verified') else 'NOT VERIFIED'}</b>\n\n"
        "⚡ Fast · Clean · Limitless\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>Use at your own risk.</b>\n"
        "🎯 For prank use with friends only.\n"
        "🛡️ We are not responsible for misuse.\n\n"
        "👇 Pick an option below."
    )


def join_required_text() -> str:
    return (
        "🔒 <b>Verification Required</b>\n\n"
        "To use <b>CF — Prank Bomber</b>, join both channels first:\n\n"
        "1️⃣ Main Channel\n"
        "2️⃣ Premium Channel\n\n"
        "After joining, tap <b>✅ Verify</b>."
    )


def menu_text(user: dict) -> str:
    return (
        "🏠 <b>Main Menu</b>\n\n"
        f"💎 Credits: <b>{user.get('credits', 0)}</b>\n"
        f"💣 Total bombs: <b>{user.get('total_bombs', 0)}</b>\n"
        f"💥 Total hits: <b>{user.get('total_hits', 0)}</b>\n\n"
        "👇 Pick an option below."
    )


def balance_text(user: dict) -> str:
    return (
        "💰 <b>Your Balance</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👤 User: <b>{user.get('first_name') or 'friend'}</b>\n"
        f"💎 Credits: <b>{user.get('credits', 0)}</b>\n"
        f"💣 Total bombs: <b>{user.get('total_bombs', 0)}</b>\n"
        f"💥 Total hits: <b>{user.get('total_hits', 0)}</b>\n"
        f"✅ Verified: <b>{'yes' if user.get('is_verified') else 'no'}</b>\n"
        f"⭐ Premium: <b>{'yes' if user.get('is_premium') else 'no'}</b>"
    )


def referral_text(user: dict, link: str, count: int) -> str:
    return (
        "👥 <b>Referral System</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📊 Your referrals: <b>{count}</b>\n"
        "💎 Each referral = <b>+2 credits</b>\n\n"
        f"🔗 Your link:\n<code>{link}</code>\n\n"
        "📝 How it works:\n"
        "• Share your link\n"
        "• New user joins → you get +2\n"
        "• They get free credits too"
    )


def bomb_category_text(phone: str) -> str:
    return (
        "🎯 <b>Bomb Setup</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📱 Target: <code>+91{phone}</code>\n\n"
        "📂 Choose category:"
    )


def bomb_duration_text(category: str, cost: int) -> str:
    return (
        "⏱ <b>Bomb Duration</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📂 Category: <b>{category.upper()}</b>\n"
        f"💎 Cost: <b>{cost} credits</b>\n\n"
        "⏱ Pick duration:"
    )


def bomb_confirm_text(phone: str, category: str, duration: int,
                       resend: bool, cost: int) -> str:
    return (
        "🎯 <b>Confirm Bomb</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📱 Target: <code>+91{phone}</code>\n"
        f"📂 Category: <b>{category.upper()}</b>\n"
        f"⏱ Duration: <b>{duration}s</b>\n"
        f"🔁 Resend: <b>{'ON' if resend else 'OFF'}</b>\n"
        f"💎 Cost: <b>{cost} credits</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "▶️ START to begin"
    )


def bomb_progress_text(p: dict) -> str:
    return (
        "🛰️ <b>BOMBING LIVE</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📱 Target: <code>+91{p['phone']}</code>\n"
        f"⏱ Elapsed: <b>{p['elapsed']}s</b> · Remaining: <b>{p['remaining']}s</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💥 Hits: <b>{p['hits']}</b>\n"
        f"❌ Fails: <b>{p['fails']}</b>\n"
        f"🔁 Resends: <b>{p.get('resends', 0)}</b>\n"
        f"🎯 APIs fired: <b>{p['apis_fired']}</b>\n"
        f"🔄 Tick: <b>{p['tick']}</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "🛑 Tap STOP to end early"
    )


def bomb_final_text(phone: str, hits: int, resends: int,
                    duration: int, balance: int, ticks: int) -> str:
    return (
        "✅ <b>BOMB COMPLETE</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📱 Target: <code>+91{phone}</code>\n"
        f"💥 Total hits: <b>{hits}</b>\n"
        f"🔁 Resends: <b>{resends}</b>\n"
        f"⏱ Duration: <b>{duration}s</b>\n"
        f"🔄 Ticks: <b>{ticks}</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💎 Credits left: <b>{balance}</b>\n\n"
        "🖤 CF — Prank Bomber"
    )


def redeem_prompt_text() -> str:
    return (
        "🎟️ <b>Redeem Code</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Send your code:\n"
        "Example: <code>CF-XXXX-XXXX</code>"
    )


def redeem_result_text(ok: bool, msg: str, credits: int, balance: int) -> str:
    if ok:
        return (
            "✅ <b>Code Redeemed</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            f"💎 Credits added: <b>+{credits}</b>\n"
            f"💰 New balance: <b>{balance}</b>"
        )
    return (
        "❌ <b>Redemption Failed</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"{msg}\n"
        f"💰 Balance: <b>{balance}</b>"
    )


def custom_bomber_text() -> str:
    return (
        "💼 <b>Custom Bomber Access</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🔒 Need a private / custom setup?\n\n"
        "💎 <b>₹500 / month</b> — priority queue + custom payloads\n"
        "🏆 <b>₹1,000 / month</b> — VIP all-access (exclusive APIs, no queue)\n\n"
        "📩 Contact: <b>@ownerVortex525</b>"
    )


def admin_panel_text(stats: dict) -> str:
    apis = stats.get("apis", {})
    px = stats.get("proxies", {})
    cd = stats.get("codes", {})
    resend = stats.get("resend_mode")
    resend_line = ""
    if resend is not None:
        resend_line = f"🔁 Resend mode: <b>{'ON' if resend else 'OFF'}</b>\n"
    return (
        "👑 <b>CF — ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👥 Users: <b>{stats.get('users', 0)}</b>\n"
        f"🔌 APIs healthy: <b>{apis.get('healthy', 0)}/{apis.get('total', 0)}</b>\n"
        f"🌐 Proxies alive: <b>{px.get('alive', 0)}/{px.get('total', 0)}</b>\n"
        f"🎟️ Codes total: <b>{cd.get('total', 0)}</b>\n"
        f"🎟️ Codes used: <b>{cd.get('used', 0)}</b>\n"
        f"💎 Credits redeemed: <b>{cd.get('credits_redeemed', 0)}</b>\n"
        f"{resend_line}"
        "━━━━━━━━━━━━━━━━\n"
        "👇 Select an option."
    )