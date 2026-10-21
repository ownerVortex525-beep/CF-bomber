import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Missing required env: {key}")
    return v.strip()


def _int(key: str, default: int = 0) -> int:
    v = os.getenv(key)
    if not v:
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


BOT_TOKEN = _req("BOT_TOKEN")
OWNER_ID = _int("OWNER_ID", 0)
if OWNER_ID <= 0:
    raise RuntimeError("OWNER_ID must be a positive integer")

CHANNEL_1_ID = _int("CHANNEL_1_ID", 0)
CHANNEL_2_ID = _int("CHANNEL_2_ID", 0)
CHANNEL_1_URL = os.getenv("CHANNEL_1_URL", "").strip()
CHANNEL_2_URL = os.getenv("CHANNEL_2_URL", "").strip()

if not CHANNEL_1_ID or not CHANNEL_2_ID:
    raise RuntimeError("CHANNEL_1_ID and CHANNEL_2_ID are required")
if not CHANNEL_1_URL or not CHANNEL_2_URL:
    raise RuntimeError("CHANNEL_1_URL and CHANNEL_2_URL are required")

CHANNEL_IDS = [CHANNEL_1_ID, CHANNEL_2_ID]
CHANNEL_URLS = [CHANNEL_1_URL, CHANNEL_2_URL]

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "cf_bomber.db"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", str(BASE_DIR / "cf_bomber.log"))

BOMB_TICK_SECONDS = float(os.getenv("BOMB_TICK_SECONDS", "2.0"))
GLOBAL_CONCURRENCY = _int("GLOBAL_CONCURRENCY", 60)
PER_HOST_CONCURRENCY = _int("PER_HOST_CONCURRENCY", 3)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "6.0"))
MAX_RETRIES = _int("MAX_RETRIES", 2)

# Hot API pool: how many healthy APIs to keep loaded per bomb tick
HOT_POOL_SIZE = _int("HOT_POOL_SIZE", 5)

PROXY_CHECK_INTERVAL = _int("PROXY_CHECK_INTERVAL", 1800)
PROXY_LOW_HEALTH = _int("PROXY_LOW_HEALTH", 20)

BROADCAST_BATCH_SIZE = _int("BROADCAST_BATCH_SIZE", 25)
BROADCAST_SLEEP = float(os.getenv("BROADCAST_SLEEP", "0.05"))

CODE_CLEANUP_INTERVAL_HOURS = _int("CODE_CLEANUP_INTERVAL_HOURS", 6)
CODE_CLEANUP_DAYS = _int("CODE_CLEANUP_DAYS", 7)

DEFAULT_COOLDOWN = _int("DEFAULT_COOLDOWN", 60)
DEFAULT_FREE_CREDITS = _int("DEFAULT_FREE_CREDITS", 5)
DEFAULT_REFERRAL_CREDITS = _int("DEFAULT_REFERRAL_CREDITS", 2)