import asyncio
import logging
import os
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from config import (
    BOT_TOKEN, OWNER_ID, CHANNEL_IDS, CHANNEL_URLS,
    LOG_LEVEL, LOG_FILE, CODE_CLEANUP_INTERVAL_HOURS,
)
from db import init_db, close_db, recover_orphans, seed_api_stats
from bomber import init_bomber, close_bomber, _apis, api_report
import proxies
from redeem import cleanup_loop
from gate import ForceJoinMiddleware, BanMiddleware, MaintenanceMiddleware
from handlers import register_all

log = logging.getLogger("bot")
_stop_event = asyncio.Event()
_health_runner = None


def setup_logging() -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=fmt,
        handlers=handlers,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "service": "CF-Prank-Bomber",
        "bot": "running",
    })


async def stats_handler(request):
    try:
        apis = await api_report()
        px = await proxies.proxy_summary()
        return web.json_response({
            "status": "ok",
            "apis": apis,
            "proxies": px,
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def start_health_server():
    global _health_runner
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/stats", stats_handler)
    _health_runner = web.AppRunner(app)
    await _health_runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(_health_runner, "0.0.0.0", port)
    await site.start()
    log.info(f"✅ Health server on 0.0.0.0:{port}")


async def startup(bot: Bot, dp: Dispatcher) -> None:
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("💣 CF — PRANK BOMBER")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    await init_db()
    log.info("✅ DB ready")

    await init_bomber()
    log.info(f"✅ Bomber ready · {len(_apis)} APIs loaded")

    await seed_api_stats(_apis)

    await proxies.init_proxy_engine()
    summary = await proxies.proxy_summary()
    log.info(f"✅ Proxy engine ready · {summary['total']} in pool")

    recovered = await recover_orphans()
    if recovered:
        log.info(f"🔁 Recovered {recovered} orphan bombs")

    me = await bot.get_me()
    log.info(f"🤖 Bot: @{me.username} (id={me.id})")
    log.info(f"👑 Owner: {OWNER_ID}")
    log.info(f"📢 Channels: {CHANNEL_IDS}")

    await start_health_server()

    asyncio.create_task(
        proxies.proxy_watchdog_loop(_stop_event),
        name="proxy_watchdog",
    )
    asyncio.create_task(
        cleanup_loop(_stop_event, CODE_CLEANUP_INTERVAL_HOURS),
        name="code_cleanup",
    )
    log.info("✅ Background tasks started")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


async def shutdown(bot: Bot, dp: Dispatcher) -> None:
    log.info("🛑 Shutting down...")
    _stop_event.set()
    global _health_runner
    try:
        if _health_runner:
            await _health_runner.cleanup()
            log.info("✅ Health server closed")
    except Exception:
        pass
    try:
        await close_bomber()
        log.info("✅ Bomber closed")
    except Exception:
        log.exception("bomber close failed")
    try:
        await proxies.close_proxy_engine()
        log.info("✅ Proxy engine closed")
    except Exception:
        log.exception("proxy close failed")
    try:
        await close_db()
        log.info("✅ DB closed")
    except Exception:
        log.exception("db close failed")
    try:
        await bot.session.close()
        log.info("✅ Bot session closed")
    except Exception:
        pass
    log.info("👋 Goodbye.")


def _install_signal_handlers() -> None:
    def _handler(sig, frame):
        log.warning(f"Signal received: {sig}")
        _stop_event.set()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass


async def main() -> None:
    setup_logging()
    _install_signal_handlers()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(BanMiddleware())
    dp.callback_query.middleware(BanMiddleware())
    dp.message.middleware(MaintenanceMiddleware(OWNER_ID))
    dp.callback_query.middleware(MaintenanceMiddleware(OWNER_ID))
    dp.message.middleware(ForceJoinMiddleware(CHANNEL_IDS, CHANNEL_URLS, OWNER_ID))
    dp.callback_query.middleware(ForceJoinMiddleware(CHANNEL_IDS, CHANNEL_URLS, OWNER_ID))

    register_all(dp)

    await startup(bot, dp)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            handle_signals=False,
        )
    except Exception:
        log.exception("Polling crashed")
    finally:
        await shutdown(bot, dp)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        logging.getLogger("bot").exception("Fatal error")
        sys.exit(1)