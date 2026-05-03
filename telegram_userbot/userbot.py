"""
Telegram Userbot — Always Online + Auto-Reply
Built with Telethon.

دستورات (فقط خودت میتونی تایپ کنی چون outgoing هست):
  .ping            → تست زنده بودن
  .afk [متن]       → روشن/خاموش کردن حالت غایب
  .stats           → نمایش آمار ربات
  .alive           → وضعیت ربات
  .id              → نمایش آیدی چت فعلی
  .help            → لیست دستورات
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ───────────────────────── Config ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "userbot_session")
AFK_MESSAGE = os.environ.get(
    "AFK_MESSAGE",
    "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏",
)
AFK_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))  # ثانیه — هر کاربر هر ۳۰ دقیقه یک بار
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")

# ───────────────────────── State ──────────────────────────
afk_enabled = False
afk_reason: str | None = None
replied_users: dict[int, float] = {}
stats = {"start_time": time.time(), "replies_sent": 0, "messages_received": 0}

# ───────────────────────── Logging ────────────────────────
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(BASE_DIR / "userbot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("userbot")

# ───────────────────────── Client ─────────────────────────
client = TelegramClient(str(BASE_DIR / SESSION_NAME), API_ID, API_HASH)


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h}h {m}m {s}s"


# ─────────────────────── Userbot Commands ─────────────────────
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ping$"))
async def cmd_ping(event):
    t0 = time.time()
    msg = await event.edit("🏓 ...")
    latency = (time.time() - t0) * 1000
    await msg.edit(f"🏓 **Pong!** `{latency:.0f} ms`")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}afk(?:\s+(.+))?$"))
async def cmd_afk(event):
    global afk_enabled, afk_reason
    reason = event.pattern_match.group(1)

    if afk_enabled and not reason:
        afk_enabled = False
        afk_reason = None
        replied_users.clear()
        await event.edit("✅ **AFK خاموش شد.** دیگه پاسخ خودکار داده نمیشه.")
    else:
        afk_enabled = True
        afk_reason = reason if reason else AFK_MESSAGE
        await event.edit(
            "💤 **AFK روشن شد.**\n"
            f"📝 پیام پاسخ: `{afk_reason}`"
        )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    text = (
        "📊 **آمار یوزربات**\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📨 پیام‌های خصوصی دریافتی: `{stats['messages_received']}`\n"
        f"🤖 پاسخ‌های خودکار ارسالی: `{stats['replies_sent']}`\n"
        f"💤 حالت AFK: `{'روشن 🟢' if afk_enabled else 'خاموش 🔴'}`\n"
        f"⏳ Cooldown پاسخ: `{AFK_COOLDOWN}s`"
    )
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}alive$"))
async def cmd_alive(event):
    uptime = time.time() - stats["start_time"]
    await event.edit(
        "✨ **یوزربات زنده و آنلاینه**\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"💤 AFK: `{'روشن' if afk_enabled else 'خاموش'}`\n"
        f"📚 کتابخونه: `Telethon`\n"
        f"🐍 بک‌اند: `Python`"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}id$"))
async def cmd_id(event):
    chat = await event.get_chat()
    await event.edit(f"🆔 Chat ID: `{chat.id}`")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}help$"))
async def cmd_help(event):
    text = (
        "🤖 **دستورات یوزربات**\n\n"
        f"`{CMD_PREFIX}ping` — تست زنده بودن\n"
        f"`{CMD_PREFIX}afk [متن]` — روشن/خاموش کردن AFK (با متن دلخواه)\n"
        f"`{CMD_PREFIX}alive` — وضعیت ربات\n"
        f"`{CMD_PREFIX}stats` — آمار کامل\n"
        f"`{CMD_PREFIX}id` — نمایش آیدی چت فعلی\n"
        f"`{CMD_PREFIX}help` — همین راهنما"
    )
    await event.edit(text)


# ──────────────────── Auto-Reply (incoming PMs) ───────────────────
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False):
        return

    stats["messages_received"] += 1

    if not afk_enabled:
        return

    now = time.time()
    last = replied_users.get(sender.id, 0)
    if now - last < AFK_COOLDOWN:
        return

    try:
        await event.reply(afk_reason or AFK_MESSAGE)
        replied_users[sender.id] = now
        stats["replies_sent"] += 1
        logger.info(
            f"Auto-replied to {getattr(sender, 'first_name', '?')} (id={sender.id})"
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Auto-reply failed: {e}")


# ─────────────────────────── Runner ───────────────────────────
async def main():
    logger.info("Connecting to Telegram...")
    await client.start(phone=PHONE)
    me = await client.get_me()
    logger.info(f"Logged in as {me.first_name} (@{me.username}) — id={me.id}")
    print(
        "\n✅ یوزربات فعال شد!\n"
        f"   نام:      {me.first_name}\n"
        f"   یوزرنیم:  @{me.username}\n"
        f"   آیدی:     {me.id}\n"
        f"   دستورات:  {CMD_PREFIX}help\n"
    )
    await client.run_until_disconnected()


if __name__ == "__main__":
    reconnect_delay = 10
    while True:
        try:
            with client:
                client.loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("Shutdown requested. Bye 👋")
            break
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Fatal error: {exc}. Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
