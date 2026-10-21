"""
db.py — CF Prank Bomber
SQLite + WAL mode. All mutations transaction-safe.
"""
import asyncio
import aiosqlite
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

DB_PATH = Path("cf_bomber.db")

# ============================================================
# SCHEMA
# ============================================================
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- ─────────────────── USERS ───────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    credits         INTEGER DEFAULT 0,
    referred_by     INTEGER,
    joined_at       TEXT NOT NULL,
    is_verified     INTEGER DEFAULT 0,
    is_premium      INTEGER DEFAULT 0,
    is_banned       INTEGER DEFAULT 0,
    last_bomb_at    TEXT,
    total_bombs     INTEGER DEFAULT 0,
    total_hits      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_referred ON users(referred_by);
CREATE INDEX IF NOT EXISTS idx_users_banned   ON users(is_banned);

-- ─────────────────── REFERRALS ───────────────────
CREATE TABLE IF NOT EXISTS referrals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id     INTEGER NOT NULL,
    referee_id      INTEGER NOT NULL UNIQUE,
    credited_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ref_referrer ON referrals(referrer_id);

-- ─────────────────── BOMBS ───────────────────
CREATE TABLE IF NOT EXISTS bombs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    phone           TEXT NOT NULL,
    category        TEXT NOT NULL,
    duration_sec    INTEGER NOT NULL,
    resend_mode     INTEGER DEFAULT 1,
    credits_spent   INTEGER NOT NULL,
    hits            INTEGER DEFAULT 0,
    resends         INTEGER DEFAULT 0,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    status          TEXT DEFAULT 'running'
);
CREATE INDEX IF NOT EXISTS idx_bombs_user ON bombs(user_id);
CREATE INDEX IF NOT EXISTS idx_bombs_status ON bombs(status);

-- ─────────────────── API STATS ───────────────────
CREATE TABLE IF NOT EXISTS api_stats (
    api_id          TEXT PRIMARY KEY,
    host            TEXT NOT NULL,
    category        TEXT NOT NULL,
    hits_ok         INTEGER DEFAULT 0,
    hits_fail       INTEGER DEFAULT 0,
    last_used       REAL DEFAULT 0,
    health          INTEGER DEFAULT 100,
    backoff_until   REAL DEFAULT 0,
    avg_latency_ms  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_host ON api_stats(host);
CREATE INDEX IF NOT EXISTS idx_api_cat  ON api_stats(category);

-- ─────────────────── PROXIES ───────────────────
CREATE TABLE IF NOT EXISTS proxies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    scheme          TEXT NOT NULL,
    host            TEXT NOT NULL,
    port            INTEGER NOT NULL,
    username        TEXT,
    password        TEXT,
    status          TEXT DEFAULT 'unchecked',
    health          INTEGER DEFAULT 100,
    fail_streak     INTEGER DEFAULT 0,
    last_checked    REAL DEFAULT 0,
    last_used       REAL DEFAULT 0,
    added_by        INTEGER,
    added_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status);
CREATE INDEX IF NOT EXISTS idx_proxies_health ON proxies(health);

-- ─────────────────── HOST STATE ───────────────────
CREATE TABLE IF NOT EXISTS host_state (
    host                TEXT PRIMARY KEY,
    direct_banned_until REAL DEFAULT 0,
    preferred_proxy_id  INTEGER,
    success_count       INTEGER DEFAULT 0,
    fail_count          INTEGER DEFAULT 0,
    updated_at          REAL DEFAULT 0
);

-- ─────────────────── REDEEM CODES ───────────────────
CREATE TABLE IF NOT EXISTS redeem_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL UNIQUE,
    credits         INTEGER NOT NULL,
    max_uses        INTEGER NOT NULL,
    used_count      INTEGER DEFAULT 0,
    expires_at      TEXT,
    note            TEXT,
    created_by      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    is_revoked      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_codes_code ON redeem_codes(code);

CREATE TABLE IF NOT EXISTS redeem_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    credits         INTEGER NOT NULL,
    redeemed_at     TEXT NOT NULL,
    UNIQUE(code_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_redeemlog_user ON redeem_log(user_id);

-- ─────────────────── BROADCASTS ───────────────────
CREATE TABLE IF NOT EXISTS broadcasts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id        INTEGER NOT NULL,
    type            TEXT NOT NULL,
    sent_count      INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    blocked_count   INTEGER DEFAULT 0,
    started_at      TEXT NOT NULL,
    ended_at        TEXT
);

-- ─────────────────── SETTINGS ───────────────────
CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
"""

DEFAULT_SETTINGS = {
    "maintenance": "0",
    "bomb_cost_sms": "1",
    "bomb_cost_call": "2",
    "bomb_cost_whatsapp": "2",
    "bomb_cost_all": "3",
    "free_credits": "5",
    "referral_credits": "2",
    "max_concurrent_bombs": "1",
    "cooldown_seconds": "60",
}


# ============================================================
# CONNECTION MANAGER
# ============================================================
_db: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()


async def init_db() -> None:
    """Initialize DB, schema, settings. Idempotent."""
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()

    # seed default settings
    for k, v in DEFAULT_SETTINGS.items():
        await _db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (k, v),
        )
    await _db.commit()
    print(f"✅ DB initialized: {DB_PATH}")


async def close_db() -> None:
    global _db
    if _db:
        await _db.commit()
        await _db.close()
        _db = None


def conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    return _db


# ============================================================
# USERS
# ============================================================
async def get_user(user_id: int) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM users WHERE user_id=?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    referred_by: Optional[int] = None,
    free_credits: int = 5,
) -> dict:
    """Create user + handle referral atomically. Returns user dict."""
    now = datetime.utcnow().isoformat()
    async with _lock:
        await conn().execute(
            """INSERT INTO users
               (user_id, username, first_name, credits, referred_by, joined_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, first_name, free_credits, referred_by, now),
        )
        # referral credit bonus (referrer gets +N, referee already has free)
        if referred_by:
            await conn().execute(
                "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                (int(DEFAULT_SETTINGS["referral_credits"]), referred_by),
            )
            await conn().execute(
                "INSERT OR IGNORE INTO referrals(referrer_id, referee_id, credited_at)"
                " VALUES(?, ?, ?)",
                (referred_by, user_id, now),
            )
        await conn().commit()
    return await get_user(user_id)


async def set_verified(user_id: int, verified: bool = True) -> None:
    await conn().execute(
        "UPDATE users SET is_verified=? WHERE user_id=?",
        (1 if verified else 0, user_id),
    )
    await conn().commit()


async def set_banned(user_id: int, banned: bool = True) -> None:
    await conn().execute(
        "UPDATE users SET is_banned=? WHERE user_id=?",
        (1 if banned else 0, user_id),
    )
    await conn().commit()


async def set_premium(user_id: int, premium: bool = True) -> None:
    await conn().execute(
        "UPDATE users SET is_premium=? WHERE user_id=?",
        (1 if premium else 0, user_id),
    )
    await conn().commit()


async def add_credits(user_id: int, amount: int) -> int:
    """Add credits (can be negative), clamp >= 0. Returns new balance."""
    async with _lock:
        await conn().execute(
            "UPDATE users SET credits = MAX(0, credits + ?) WHERE user_id=?",
            (amount, user_id),
        )
        await conn().commit()
        async with conn().execute(
            "SELECT credits FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["credits"] if row else 0


async def deduct_credits(user_id: int, amount: int) -> bool:
    """Atomic deduct. Returns True if successful."""
    async with _lock:
        async with conn().execute(
            "SELECT credits FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row or row["credits"] < amount:
                return False
        await conn().execute(
            "UPDATE users SET credits = credits - ? WHERE user_id=?",
            (amount, user_id),
        )
        await conn().commit()
        return True


async def all_user_ids(only_verified: bool = False) -> list[int]:
    q = "SELECT user_id FROM users WHERE is_banned=0"
    if only_verified:
        q += " AND is_verified=1"
    async with conn().execute(q) as cur:
        rows = await cur.fetchall()
        return [r["user_id"] for r in rows]


async def total_users() -> int:
    async with conn().execute("SELECT COUNT(*) c FROM users") as cur:
        r = await cur.fetchone()
        return r["c"] if r else 0


# ============================================================
# BOMBS
# ============================================================
async def create_bomb(
    user_id: int, phone: str, category: str,
    duration_sec: int, resend_mode: int, credits_spent: int,
) -> int:
    now = datetime.utcnow().isoformat()
    async with _lock:
        cur = await conn().execute(
            """INSERT INTO bombs
               (user_id, phone, category, duration_sec, resend_mode,
                credits_spent, started_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'running')""",
            (user_id, phone, category, duration_sec, resend_mode,
             credits_spent, now),
        )
        await conn().execute(
            "UPDATE users SET last_bomb_at=?, total_bombs=total_bombs+1"
            " WHERE user_id=?", (now, user_id),
        )
        await conn().commit()
        return cur.lastrowid


async def finish_bomb(bomb_id: int, hits: int, resends: int) -> None:
    now = datetime.utcnow().isoformat()
    async with _lock:
        await conn().execute(
            "UPDATE bombs SET hits=?, resends=?, ended_at=?, status='done'"
            " WHERE id=?", (hits, resends, now, bomb_id),
        )
        await conn().execute(
            "UPDATE users SET total_hits = total_hits + ? WHERE user_id ="
            " (SELECT user_id FROM bombs WHERE id=?)", (hits, bomb_id),
        )
        await conn().commit()


async def orphan_bombs() -> list[dict]:
    """Bombs stuck in 'running' (bot crashed). Used at startup."""
    async with conn().execute(
        "SELECT * FROM bombs WHERE status='running'"
    ) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def recover_orphans(refund_pct: float = 0.5) -> int:
    """Mark orphan bombs done, refund % credits. Returns count recovered."""
    orphans = await orphan_bombs()
    if not orphans:
        return 0
    now = datetime.utcnow().isoformat()
    async with _lock:
        for b in orphans:
            refund = int(b["credits_spent"] * refund_pct)
            await conn().execute(
                "UPDATE bombs SET ended_at=?, status='crashed' WHERE id=?",
                (now, b["id"]),
            )
            if refund > 0:
                await conn().execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id=?",
                    (refund, b["user_id"]),
                )
        await conn().commit()
    print(f"🔁 Recovered {len(orphans)} orphan bombs")
    return len(orphans)


# ============================================================
# API STATS
# ============================================================
async def seed_api_stats(apis: list[dict]) -> None:
    """Insert API rows if not exist (idempotent)."""
    async with _lock:
        for a in apis:
            host = _extract_host(a["url"])
            await conn().execute(
                """INSERT OR IGNORE INTO api_stats
                   (api_id, host, category, health)
                   VALUES (?, ?, ?, 100)""",
                (a["id"], host, a["category"]),
            )
        await conn().commit()


async def mark_api_success(api_id: str, latency_ms: int) -> None:
    now = time.time()
    async with _lock:
        await conn().execute(
            """UPDATE api_stats SET
                 hits_ok = hits_ok + 1,
                 last_used = ?,
                 health = MIN(100, health + 2),
                 avg_latency_ms = (avg_latency_ms * 4 + ?) / 5
               WHERE api_id = ?""",
            (now, latency_ms, api_id),
        )
        await conn().commit()


async def mark_api_fail(api_id: str, status: Optional[int] = None,
                        backoff: int = 0) -> None:
    now = time.time()
    penalty = 15 if status == 429 else 5
    async with _lock:
        await conn().execute(
            """UPDATE api_stats SET
                 hits_fail = hits_fail + 1,
                 last_used = ?,
                 health = MAX(0, health - ?),
                 backoff_until = MAX(backoff_until, ?)
               WHERE api_id = ?""",
            (now, penalty, now + backoff, api_id),
        )
        await conn().commit()


async def get_api_health(api_id: str) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM api_stats WHERE api_id=?", (api_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def healthy_apis(category: Optional[str] = None) -> list[dict]:
    now = time.time()
    q = ("SELECT * FROM api_stats WHERE health >= 20"
         " AND backoff_until <= ?")
    args: list[Any] = [now]
    if category and category != "all":
        q += " AND category = ?"
        args.append(category)
    async with conn().execute(q, args) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def reset_api_health(api_id: Optional[str] = None) -> None:
    async with _lock:
        if api_id:
            await conn().execute(
                "UPDATE api_stats SET health=100, backoff_until=0"
                " WHERE api_id=?", (api_id,),
            )
        else:
            await conn().execute(
                "UPDATE api_stats SET health=100, backoff_until=0"
            )
        await conn().commit()


# ============================================================
# PROXIES
# ============================================================
async def add_proxy(url: str, added_by: int) -> bool:
    parsed = _parse_proxy(url)
    if not parsed:
        return False
    now = datetime.utcnow().isoformat()
    try:
        async with _lock:
            await conn().execute(
                """INSERT INTO proxies
                   (url, scheme, host, port, username, password,
                    status, added_by, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'unchecked', ?, ?)""",
                (url, parsed["scheme"], parsed["host"], parsed["port"],
                 parsed.get("username"), parsed.get("password"),
                 added_by, now),
            )
            await conn().commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def list_proxies() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM proxies ORDER BY health DESC, id ASC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def alive_proxies() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM proxies WHERE status='alive' AND health >= 20"
        " ORDER BY health DESC, last_used ASC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def update_proxy_status(proxy_id: int, alive: bool,
                              latency_ms: int = 0) -> None:
    now = time.time()
    async with _lock:
        if alive:
            await conn().execute(
                """UPDATE proxies SET
                     status='alive', health=MIN(100, health + 10),
                     fail_streak=0, last_checked=?
                   WHERE id=?""",
                (now, proxy_id),
            )
        else:
            await conn().execute(
                """UPDATE proxies SET
                     fail_streak = fail_streak + 1,
                     health = MAX(0, health - 20),
                     last_checked = ?,
                     status = CASE WHEN fail_streak + 1 >= 3
                                   THEN 'dead' ELSE status END
                   WHERE id=?""",
                (now, proxy_id),
            )
        await conn().commit()


async def mark_proxy_used(proxy_id: int) -> None:
    await conn().execute(
        "UPDATE proxies SET last_used=? WHERE id=?", (time.time(), proxy_id)
    )
    await conn().commit()


async def remove_dead_proxies() -> int:
    async with _lock:
        cur = await conn().execute("DELETE FROM proxies WHERE status='dead'")
        await conn().commit()
        return cur.rowcount or 0


# ============================================================
# HOST STATE
# ============================================================
async def get_host_state(host: str) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM host_state WHERE host=?", (host,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def ban_host_direct(host: str, seconds: int = 300) -> None:
    until = time.time() + seconds
    async with _lock:
        await conn().execute(
            """INSERT INTO host_state (host, direct_banned_until, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(host) DO UPDATE SET
                 direct_banned_until = excluded.direct_banned_until,
                 updated_at = excluded.updated_at""",
            (host, until, time.time()),
        )
        await conn().commit()


async def host_direct_banned(host: str) -> bool:
    async with conn().execute(
        "SELECT direct_banned_until FROM host_state WHERE host=?", (host,)
    ) as cur:
        row = await cur.fetchone()
        if not row:
            return False
        return row["direct_banned_until"] > time.time()


# ============================================================
# REDEEM CODES
# ============================================================
async def create_code(
    code: str, credits: int, max_uses: int,
    expires_at: Optional[str], note: Optional[str], created_by: int,
) -> int:
    now = datetime.utcnow().isoformat()
    async with _lock:
        cur = await conn().execute(
            """INSERT INTO redeem_codes
               (code, credits, max_uses, expires_at, note,
                created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, credits, max_uses, expires_at, note, created_by, now),
        )
        await conn().commit()
        return cur.lastrowid


async def get_code(code: str) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM redeem_codes WHERE code=?", (code,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def redeem_code(code_str: str, user_id: int) -> tuple[bool, str, int]:
    """
    Atomic redeem. Returns (ok, message, credits_granted).
    """
    async with _lock:
        async with conn().execute(
            "SELECT * FROM redeem_codes WHERE code=?", (code_str,)
        ) as cur:
            code = await cur.fetchone()
            if not code:
                return False, "❌ Invalid code.", 0
            code = dict(code)

            if code["is_revoked"]:
                return False, "❌ Code revoked.", 0

            if code["expires_at"] and code["expires_at"] < datetime.utcnow().isoformat():
                return False, "❌ Code expired.", 0

            if code["used_count"] >= code["max_uses"]:
                return False, "❌ Code limit reached.", 0

            # one user = one redeem per code
            async with conn().execute(
                "SELECT 1 FROM redeem_log WHERE code_id=? AND user_id=?",
                (code["id"], user_id),
            ) as cur:
                if await cur.fetchone():
                    return False, "❌ You already redeemed this code.", 0

            now = datetime.utcnow().isoformat()
            await conn().execute(
                "INSERT INTO redeem_log(code_id, user_id, credits, redeemed_at)"
                " VALUES(?, ?, ?, ?)",
                (code["id"], user_id, code["credits"], now),
            )
            await conn().execute(
                "UPDATE redeem_codes SET used_count = used_count + 1 WHERE id=?",
                (code["id"],),
            )
            await conn().execute(
                "UPDATE users SET credits = credits + ? WHERE user_id=?",
                (code["credits"], user_id),
            )
            await conn().commit()
            return True, f"✅ +{code['credits']} credits added!", code["credits"]


async def revoke_code(code: str) -> bool:
    async with _lock:
        cur = await conn().execute(
            "UPDATE redeem_codes SET is_revoked=1 WHERE code=? AND is_revoked=0",
            (code,),
        )
        await conn().commit()
        return (cur.rowcount or 0) > 0


async def list_codes() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM redeem_codes ORDER BY id DESC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def cleanup_expired_codes(days: int = 7) -> int:
    """Purge spent/expired/revoked codes older than N days."""
    cutoff = datetime.utcnow().isoformat()
    age_cutoff = (datetime.utcnow().replace(microsecond=0))
    from datetime import timedelta
    age_cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with _lock:
        cur = await conn().execute(
            """DELETE FROM redeem_codes
               WHERE (used_count >= max_uses
                      OR (expires_at IS NOT NULL AND expires_at < ?)
                      OR is_revoked = 1)
                 AND created_at < ?""",
            (cutoff, age_cutoff),
        )
        await conn().commit()
        n = cur.rowcount or 0
        if n:
            print(f"🧹 Cleaned {n} expired codes")
        return n


async def code_stats() -> dict:
    async with conn().execute(
        "SELECT COUNT(*) total,"
        " SUM(used_count) used,"
        " SUM(CASE WHEN used_count >= max_uses THEN 1 ELSE 0 END) exhausted"
        " FROM redeem_codes"
    ) as cur:
        row = await cur.fetchone()
        d = dict(row)
    async with conn().execute(
        "SELECT SUM(credits) c FROM redeem_log"
    ) as cur:
        row = await cur.fetchone()
        d["credits_redeemed"] = row["c"] or 0
    return d


# ============================================================
# BROADCASTS
# ============================================================
async def start_broadcast(admin_id: int, btype: str) -> int:
    now = datetime.utcnow().isoformat()
    async with _lock:
        cur = await conn().execute(
            "INSERT INTO broadcasts(admin_id, type, started_at)"
            " VALUES(?, ?, ?)",
            (admin_id, btype, now),
        )
        await conn().commit()
        return cur.lastrowid


async def update_broadcast(bid: int, sent: int, fail: int, blocked: int,
                           done: bool = False) -> None:
    ended = datetime.utcnow().isoformat() if done else None
    async with _lock:
        await conn().execute(
            "UPDATE broadcasts SET sent_count=?, fail_count=?,"
            " blocked_count=?, ended_at=COALESCE(?, ended_at)"
            " WHERE id=?",
            (sent, fail, blocked, ended, bid),
        )
        await conn().commit()


# ============================================================
# SETTINGS
# ============================================================
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with conn().execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ) as cur:
        row = await cur.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    async with _lock:
        await conn().execute(
            "INSERT INTO settings(key, value) VALUES(?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await conn().commit()


# ============================================================
# HELPERS
# ============================================================
def _extract_host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or "unknown"
    except Exception:
        return "unknown"


def _parse_proxy(url: str) -> Optional[dict]:
    try:
        from urllib.parse import urlparse
        if "://" not in url:
            # ip:port or ip:port:user:pass
            parts = url.split(":")
            if len(parts) == 2:
                return {"scheme": "http", "host": parts[0],
                        "port": int(parts[1])}
            if len(parts) == 4:
                return {"scheme": "http", "host": parts[0],
                        "port": int(parts[1]),
                        "username": parts[2], "password": parts[3]}
            return None
        p = urlparse(url)
        return {
            "scheme": p.scheme or "http",
            "host": p.hostname,
            "port": p.port or 8080,
            "username": p.username,
            "password": p.password,
        }
    except Exception:
        return None