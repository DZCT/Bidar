"""
Bidar — یوزربات تلگرام همیشه آنلاین 🌙
============================================

یه یوزربات ساده و امن با Telethon که اکانت تلگرامت رو دائمی آنلاین
نگه میداره و یه سری قابلیت هوشمند بهت میده.

امنیت:
    - همه دستورات فقط وقتی خود مالک اکانت تایپ کنه کار میکنن
      (چک دوگانه: outgoing=True + sender_id == OWNER_ID)
    - هیچ کس دیگه‌ای نمیتونه با فرستادن دستور به شما کنترلش کنه.

لیست دستورات رو با .help ببین.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ───────────────────────── پیکربندی ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
AFK_MESSAGE = os.environ.get(
    "AFK_MESSAGE",
    "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏",
)
AFK_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))  # ثانیه
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.0.0"

# ─────────────── وضعیت در زمان اجرا (in-memory state) ───────────────
OWNER_ID: int | None = None              # بعد از لاگین پر میشه
afk_enabled: bool = False
afk_reason: str | None = None
replied_users: dict[int, float] = {}
stats = {"start_time": time.time(), "replies_sent": 0, "messages_received": 0}

# ───────────────────────── لاگ ─────────────────────────
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(BASE_DIR / "bidar.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bidar")

# ───────────────────────── کلاینت ─────────────────────────
client = TelegramClient(str(BASE_DIR / SESSION_NAME), API_ID, API_HASH)


# ───────────────────────── کمکی‌ها ─────────────────────────
def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _is_owner(event) -> bool:
    """
    بررسی امنیتی: مطمئن شو دستور از طرف مالک واقعی اکانت اومده.
    حتی اگه به هر دلیلی outgoing=True دور زده بشه، این لایه اضافی
    جلوی اجرای دستور رو میگیره.
    """
    return OWNER_ID is not None and event.sender_id == OWNER_ID


def owner_only(handler):
    """دکوریتور برای قفل کردن دستورات روی مالک اکانت."""
    async def wrapper(event):
        if not _is_owner(event):
            log.warning(
                f"⛔ تلاش دسترسی غیرمجاز توسط {event.sender_id} به {handler.__name__}"
            )
            return
        await handler(event)
    wrapper.__name__ = handler.__name__
    return wrapper


# ─────────────────────── دستورات یوزربات ─────────────────────
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ping$"))
@owner_only
async def cmd_ping(event):
    t0 = time.time()
    msg = await event.edit("🏓 ...")
    latency = (time.time() - t0) * 1000
    await msg.edit(f"🏓 **Pong!** `{latency:.0f} ms`")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}afk(?:\s+(.+))?$"))
@owner_only
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
            f"📝 پیام پاسخ خودکار:\n`{afk_reason}`"
        )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
@owner_only
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    text = (
        "📊 **آمار Bidar**\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📨 پیام‌های خصوصی دریافتی: `{stats['messages_received']}`\n"
        f"🤖 پاسخ‌های خودکار ارسالی: `{stats['replies_sent']}`\n"
        f"💤 حالت AFK: `{'روشن 🟢' if afk_enabled else 'خاموش 🔴'}`\n"
        f"⏳ Cooldown پاسخ به هر نفر: `{AFK_COOLDOWN}s`"
    )
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}alive$"))
@owner_only
async def cmd_alive(event):
    uptime = time.time() - stats["start_time"]
    await event.edit(
        "✨ **Bidar زنده و آنلاینه** 🌙\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"💤 AFK: `{'روشن' if afk_enabled else 'خاموش'}`\n"
        f"🔖 نسخه: `v{VERSION}`\n"
        f"📚 کتابخونه: `Telethon`"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}id$"))
@owner_only
async def cmd_id(event):
    chat = await event.get_chat()
    reply_txt = f"🆔 Chat ID: `{chat.id}`"
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id:
            reply_txt += f"\n👤 User ID (reply): `{replied.sender_id}`"
    await event.edit(reply_txt)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}restart$"))
@owner_only
async def cmd_restart(event):
    await event.edit("♻️ در حال ری‌استارت... (systemd دوباره بالا میاره)")
    log.info("Restart command received. Disconnecting so systemd restarts us.")
    await client.disconnect()


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(help|menu|commands)$"))
@owner_only
async def cmd_help(event):
    text = (
        "🤖 **Bidar — راهنمای کامل دستورات**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔹 **مدیریت وضعیت**\n"
        f"  `{CMD_PREFIX}alive` — بررسی اینکه ربات زنده و آنلاینه؟\n"
        f"  `{CMD_PREFIX}ping` — تست تاخیر پاسخ ربات به میلی‌ثانیه\n"
        f"  `{CMD_PREFIX}stats` — نمایش آمار کامل (آپ‌تایم، پیام‌ها، پاسخ‌ها)\n\n"
        "🔹 **حالت غایب (AFK)**\n"
        f"  `{CMD_PREFIX}afk` — روشن/خاموش کردن حالت غایب با متن پیش‌فرض\n"
        f"  `{CMD_PREFIX}afk <متن>` — روشن کردن AFK با متن دلخواه\n"
        "  ⚠️ وقتی AFK روشنه، هر کس بهت پیام خصوصی بده،\n"
        "     پیام اتوماتیک دریافت میکنه (با cooldown برای جلوگیری از اسپم).\n\n"
        "🔹 **ابزارها**\n"
        f"  `{CMD_PREFIX}id` — نمایش آیدی چت فعلی (و آیدی کاربر اگه روی پیامی ریپلای بزنی)\n"
        f"  `{CMD_PREFIX}restart` — ری‌استارت ربات (فقط در حالت systemd)\n"
        f"  `{CMD_PREFIX}help` | `{CMD_PREFIX}menu` | `{CMD_PREFIX}commands` — همین راهنما\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 همه دستورات فقط وقتی خودت تایپ کنی کار میکنن.\n"
        f"🔖 نسخه: v{VERSION}"
    )
    await event.edit(text)


# ──────────────────── پاسخ خودکار به پیام‌های خصوصی ───────────────────
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False):
        return
    if OWNER_ID is not None and sender.id == OWNER_ID:
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
        log.info(
            f"Auto-replied to {getattr(sender, 'first_name', '?')} (id={sender.id})"
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Auto-reply failed: {e}")


# ─────────────────────────── اجرا ───────────────────────────
async def main():
    global OWNER_ID
    log.info("در حال اتصال به تلگرام...")
    await client.start(phone=PHONE)
    me = await client.get_me()
    OWNER_ID = me.id
    log.info(f"✅ لاگین شد: {me.first_name} (@{me.username}) — id={me.id}")
    print(
        "\n🌙 Bidar فعال شد!\n"
        f"   نام:     {me.first_name}\n"
        f"   یوزرنیم: @{me.username}\n"
        f"   آیدی:    {me.id}\n"
        f"   دستورات: {CMD_PREFIX}help\n"
    )
    await client.run_until_disconnected()


if __name__ == "__main__":
    reconnect_delay = 10
    while True:
        try:
            with client:
                client.loop.run_until_complete(main())
            log.info("Disconnected cleanly. Exiting loop.")
            break
        except KeyboardInterrupt:
            log.info("Shutdown requested. Bye 👋")
            break
        except Exception as exc:  # noqa: BLE001
            log.error(f"Fatal error: {exc}. Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
