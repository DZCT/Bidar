"""
Bidar — یوزربات تلگرام همیشه آنلاین 🌙
============================================

امکانات:
  • آنلاین واقعی (با UpdateStatusRequest هر ۴ دقیقه)
  • پاسخ خودکار قابل تنظیم با cooldown هوشمند
  • تنظیمات قابل ویرایش در زمان اجرا با دستور (و ذخیره پایدار در JSON)
  • قفل مالکیت دوگانه: همه دستورات فقط برای خود مالک

دستورات رو با .help ببین.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateStatusRequest

# ───────────────────────── پیکربندی پایه (.env) ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.1.0"

DEFAULT_AUTOREPLY = os.environ.get(
    "AFK_MESSAGE",
    "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏",
)
DEFAULT_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))
ONLINE_REFRESH_INTERVAL = 240  # ثانیه — تلگرام هر ~۵ دقیقه آفلاینت میکنه

# ───────────────────────── تنظیمات پایدار (JSON) ─────────────────────────
CONFIG_FILE = BASE_DIR / "bidar_config.json"

_DEFAULT_CONFIG = {
    "online_enabled": True,
    "autoreply_enabled": False,
    "autoreply_message": DEFAULT_AUTOREPLY,
    "autoreply_cooldown": DEFAULT_COOLDOWN,
}

config: dict = dict(_DEFAULT_CONFIG)


def load_config() -> None:
    global config
    base = dict(_DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            base.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning(f"خطا در خوندن config؛ پیش‌فرض استفاده میشه: {e}")
    config = base


def save_config() -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"ذخیره config ناموفق بود: {e}")


# ─────────────── وضعیت در زمان اجرا (in-memory) ───────────────
OWNER_ID: int | None = None
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

load_config()

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
    return OWNER_ID is not None and event.sender_id == OWNER_ID


def owner_only(handler):
    """دکوریتور امنیتی: دستور فقط برای مالک اکانت."""
    async def wrapper(event):
        if not _is_owner(event):
            log.warning(
                f"⛔ تلاش غیرمجاز توسط {event.sender_id} به {handler.__name__}"
            )
            return
        await handler(event)
    wrapper.__name__ = handler.__name__
    return wrapper


def _parse_on_off(arg: str | None, current: bool) -> bool:
    """ورودی on/off رو به bool تبدیل میکنه؛ اگه arg نداشت toggle میکنه."""
    if arg is None:
        return not current
    return arg.strip().lower() in {"on", "روشن", "1", "true", "yes"}


# ─────────────────────── تسک پس‌زمینه: آنلاین نگه دار ─────────────────────
async def online_keeper() -> None:
    """
    هر ONLINE_REFRESH_INTERVAL ثانیه یه بار وضعیت آنلاین رو رفرش میکنه.
    بدون این، بعد از ~۵ دقیقه از نظر دیگران آفلاین نشون داده میشی.
    """
    await asyncio.sleep(3)
    last_sent_offline: bool | None = None
    while True:
        try:
            desired_offline = not config["online_enabled"]
            # اگه تغییر کرده یا روشنه (باید رفرش بشه)، درخواست بفرست
            if desired_offline != last_sent_offline or not desired_offline:
                await client(UpdateStatusRequest(offline=desired_offline))
                last_sent_offline = desired_offline
                if desired_offline:
                    log.info("📴 وضعیت: آفلاین")
                else:
                    log.debug("🟢 وضعیت آنلاین رفرش شد")
        except Exception as e:  # noqa: BLE001
            log.error(f"online_keeper: {e}")
        await asyncio.sleep(ONLINE_REFRESH_INTERVAL)


# ─────────────────────── دستورات یوزربات ─────────────────────
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ping$"))
@owner_only
async def cmd_ping(event):
    t0 = time.time()
    msg = await event.edit("🏓 ...")
    latency = (time.time() - t0) * 1000
    await msg.edit(f"🏓 **Pong!** `{latency:.0f} ms`")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}online(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_online(event):
    arg = event.pattern_match.group(1)
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config["online_enabled"],
    )
    config["online_enabled"] = new
    save_config()
    # اعمال فوری
    try:
        await client(UpdateStatusRequest(offline=not new))
    except Exception as e:  # noqa: BLE001
        log.error(f"UpdateStatusRequest: {e}")
    await event.edit(
        f"📡 **آنلاین دائم: {'روشن 🟢' if new else 'خاموش 🔴'}**\n"
        f"_بر اساس تنظیمات privacy تلگرامت نمایش داده میشه._"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}reply(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_reply(event):
    arg = event.pattern_match.group(1)
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config["autoreply_enabled"],
    )
    config["autoreply_enabled"] = new
    replied_users.clear()
    save_config()
    await event.edit(
        f"🤖 **پاسخ خودکار: {'روشن 🟢' if new else 'خاموش 🔴'}**\n"
        f"📝 متن فعلی:\n`{config['autoreply_message']}`"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}setmsg\s+([\s\S]+)$"))
@owner_only
async def cmd_setmsg(event):
    new_msg = event.pattern_match.group(1).strip()
    config["autoreply_message"] = new_msg
    save_config()
    await event.edit(
        "✅ **متن پاسخ خودکار آپدیت شد**\n\n"
        f"📝 متن جدید:\n`{new_msg}`"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}afk(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_afk(event):
    """میانبر: `.afk <متن>` متن رو آپدیت + پاسخ خودکار روشن
       `.afk` بدون آرگومان → toggle پاسخ خودکار"""
    reason = event.pattern_match.group(1)
    reason_l = reason.strip().lower() if reason else None

    if reason_l in {"off", "خاموش"}:
        config["autoreply_enabled"] = False
        replied_users.clear()
        save_config()
        await event.edit("✅ **AFK خاموش شد.**")
        return

    if reason and reason_l not in {"on", "روشن"}:
        # متن جدید دریافت شد → ذخیره + روشن کردن
        config["autoreply_message"] = reason.strip()

    config["autoreply_enabled"] = True
    save_config()
    await event.edit(
        "💤 **AFK روشن شد.**\n"
        f"📝 پیام:\n`{config['autoreply_message']}`"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
@owner_only
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    text = (
        "📊 **آمار و تنظیمات Bidar**\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📡 آنلاین دائم: `{'روشن 🟢' if config['online_enabled'] else 'خاموش 🔴'}`\n"
        f"🤖 پاسخ خودکار: `{'روشن 🟢' if config['autoreply_enabled'] else 'خاموش 🔴'}`\n"
        f"📨 پیام‌های خصوصی دریافتی: `{stats['messages_received']}`\n"
        f"✉️ پاسخ‌های خودکار ارسالی: `{stats['replies_sent']}`\n"
        f"⏳ Cooldown پاسخ: `{config['autoreply_cooldown']}s`\n\n"
        f"📝 متن پاسخ خودکار:\n`{config['autoreply_message']}`"
    )
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}alive$"))
@owner_only
async def cmd_alive(event):
    uptime = time.time() - stats["start_time"]
    await event.edit(
        "✨ **Bidar زنده و آنلاینه** 🌙\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📡 آنلاین دائم: `{'روشن' if config['online_enabled'] else 'خاموش'}`\n"
        f"🤖 پاسخ خودکار: `{'روشن' if config['autoreply_enabled'] else 'خاموش'}`\n"
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
    log.info("Restart command → disconnecting.")
    await client.disconnect()


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(help|menu|commands)$"))
@owner_only
async def cmd_help(event):
    text = (
        "🤖 **Bidar — راهنمای کامل دستورات**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔹 **وضعیت آنلاین**\n"
        f"  `{CMD_PREFIX}online on` — آنلاین دائم روشن\n"
        f"  `{CMD_PREFIX}online off` — خاموش (آفلاین نشون داده میشی)\n"
        f"  `{CMD_PREFIX}online` — جابه‌جا (toggle)\n"
        "  ℹ️ با روشن بودن این، هر ۴ دقیقه وضعیتت رفرش میشه\n"
        "     تا همیشه برای بقیه «آنلاین» نشون بدی.\n\n"
        "🔹 **پاسخ خودکار**\n"
        f"  `{CMD_PREFIX}reply on` — پاسخ خودکار روشن\n"
        f"  `{CMD_PREFIX}reply off` — خاموش\n"
        f"  `{CMD_PREFIX}reply` — جابه‌جا (toggle)\n"
        f"  `{CMD_PREFIX}setmsg <متن>` — ویرایش متن پاسخ خودکار\n"
        f"  `{CMD_PREFIX}afk <متن>` — میانبر: ست متن + روشن کردن پاسخ\n"
        f"  `{CMD_PREFIX}afk off` — خاموش کردن سریع\n\n"
        "🔹 **اطلاعات**\n"
        f"  `{CMD_PREFIX}alive` — چک زنده بودن ربات\n"
        f"  `{CMD_PREFIX}ping` — تست تاخیر (ms)\n"
        f"  `{CMD_PREFIX}stats` — همه آمار و تنظیمات فعلی\n"
        f"  `{CMD_PREFIX}id` — آیدی چت (و یوزر اگه ریپلای بزنی)\n\n"
        "🔹 **مدیریت**\n"
        f"  `{CMD_PREFIX}restart` — ری‌استارت (در حالت systemd)\n"
        f"  `{CMD_PREFIX}help` | `{CMD_PREFIX}menu` | `{CMD_PREFIX}commands` — همین راهنما\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 همه دستورات فقط برای خودت کار میکنن.  🔖 v{VERSION}"
    )
    await event.edit(text)


# ──────────────────── پاسخ خودکار به پیام‌های خصوصی ───────────────────
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    if not event.is_private:
        return
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    if OWNER_ID is not None and sender.id == OWNER_ID:
        return

    stats["messages_received"] += 1

    if not config["autoreply_enabled"]:
        return

    now = time.time()
    last = replied_users.get(sender.id, 0)
    if now - last < config["autoreply_cooldown"]:
        return

    try:
        await event.reply(config["autoreply_message"])
        replied_users[sender.id] = now
        stats["replies_sent"] += 1
        log.info(
            f"پاسخ خودکار به {getattr(sender, 'first_name', '?')} (id={sender.id})"
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"پاسخ خودکار ناموفق: {e}")


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
        f"   آنلاین دائم: {'روشن 🟢' if config['online_enabled'] else 'خاموش 🔴'}\n"
        f"   پاسخ خودکار: {'روشن 🟢' if config['autoreply_enabled'] else 'خاموش 🔴'}\n"
    )
    # تسک‌های پس‌زمینه
    asyncio.create_task(online_keeper())
    await client.run_until_disconnected()


if __name__ == "__main__":
    reconnect_delay = 10
    while True:
        try:
            with client:
                client.loop.run_until_complete(main())
            log.info("Disconnected cleanly.")
            break
        except KeyboardInterrupt:
            log.info("Shutdown requested. Bye 👋")
            break
        except Exception as exc:  # noqa: BLE001
            log.error(f"Fatal error: {exc}. Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
