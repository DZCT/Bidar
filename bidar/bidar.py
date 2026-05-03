"""
Bidar — یوزربات تلگرام همیشه آنلاین با دستیار AI 🌙🤖
============================================================

امکانات:
  • آنلاین واقعی (UpdateStatusRequest دوره‌ای)
  • پاسخ خودکار ثابت یا هوشمند با GPT/Claude/Gemini (Emergent Universal Key)
  • حفظ context مکالمه در چت خصوصی و گروه
  • در گروه: فقط موقع mention یا reply پاسخ میده
  • تنظیمات پایدار JSON و قابل ویرایش از داخل چت
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

# Optional: AI integration via Emergent Universal Key
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    AI_LIB_OK = True
except ImportError:  # کتابخونه نصب نباشه، AI غیرفعال میشه
    AI_LIB_OK = False
    LlmChat = None  # type: ignore
    UserMessage = None  # type: ignore

# ───────────────────────── پیکربندی پایه (.env) ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.3.1"

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "").strip()

DEFAULT_AUTOREPLY = os.environ.get(
    "AFK_MESSAGE",
    "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏",
)
DEFAULT_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))
DEFAULT_ONLINE_INTERVAL = 240
MIN_ONLINE_INTERVAL = 30
MAX_ONLINE_INTERVAL = 300
GROUP_REPLY_COOLDOWN = 30  # ثانیه — در گروه به همون نفر/چت

DEFAULT_AI_PERSONALITY = (
    "این پیام از طرف یک شخص است که می‌خواهد با صاحب اکانت صحبت کند. "
    "صاحب اکانت در حال حاضر در دسترس نیست و شما از طرف او پاسخ می‌دهید. "
    "جایگزین صاحب اکانت شو و به صورت طبیعی، کوتاه، مودب و دوستانه پاسخ بده. "
    "خودت را به عنوان ربات، هوش مصنوعی یا دستیار معرفی نکن — جوری رفتار کن "
    "که انگار صاحب اکانت هستی و فقط نمی‌تونی الان طولانی جواب بدی. "
    "اگر کسی پرسید کی برمی‌گردی یا در دسترس میشی، بگو «به زودی» یا «خبر می‌دم». "
    "از زبان کاربر (فارسی/انگلیسی) استفاده کن که بهت پیام داده. "
    "در گروه‌ها، فضای مکالمه را در نظر بگیر و مناسب جواب بده."
)

# ───────────────────────── تنظیمات پایدار (JSON) ─────────────────────────
CONFIG_FILE = BASE_DIR / "bidar_config.json"

_DEFAULT_CONFIG = {
    "online_enabled": True,
    "autoreply_enabled": False,
    "autoreply_message": DEFAULT_AUTOREPLY,
    "autoreply_cooldown": DEFAULT_COOLDOWN,
    "online_refresh_interval": DEFAULT_ONLINE_INTERVAL,
    # AI
    "ai_enabled": False,
    "ai_model": "gemini-3-flash-preview",
    "ai_personality": DEFAULT_AI_PERSONALITY,
    "ai_groups_enabled": False,
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
replied_users: dict[int | str, float] = {}  # برای cooldown (int برای private, str برای groups)
stats = {
    "start_time": time.time(),
    "replies_sent": 0,
    "messages_received": 0,
    "ai_replies": 0,
}

# session_id -> LlmChat instance
_chat_sessions: dict[str, object] = {}

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
    if arg is None:
        return not current
    return arg.strip().lower() in {"on", "روشن", "1", "true", "yes"}


def _infer_provider(model: str) -> str:
    """بر اساس اسم مدل، ارائه‌دهنده رو تشخیص میده."""
    m = (model or "").lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return "gemini"  # پیش‌فرض


def _ai_ready() -> tuple[bool, str]:
    if not AI_LIB_OK:
        return False, "کتابخونه emergentintegrations نصب نیست"
    if not EMERGENT_LLM_KEY:
        return False, "EMERGENT_LLM_KEY در .env ست نشده"
    return True, ""


def _reset_chat_sessions() -> None:
    _chat_sessions.clear()


def _get_chat_session(session_id: str):
    if session_id in _chat_sessions:
        return _chat_sessions[session_id]
    provider = _infer_provider(config["ai_model"])
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=config["ai_personality"],
    ).with_model(provider, config["ai_model"])
    _chat_sessions[session_id] = chat
    return chat


async def _ai_respond(session_id: str, user_text: str) -> str | None:
    ready, _ = _ai_ready()
    if not ready:
        return None
    text = (user_text or "").strip()
    if not text:
        return None
    try:
        chat = _get_chat_session(session_id)
        resp = await chat.send_message(UserMessage(text=text))
        stats["ai_replies"] += 1
        return str(resp).strip()
    except Exception as e:  # noqa: BLE001
        log.error(f"AI error on {session_id}: {e}")
        return None


# ─────────────────────── تسک پس‌زمینه: آنلاین نگه دار ─────────────────────
async def online_keeper() -> None:
    await asyncio.sleep(3)
    last_sent_offline: bool | None = None
    while True:
        try:
            desired_offline = not config["online_enabled"]
            if desired_offline != last_sent_offline or not desired_offline:
                await client(UpdateStatusRequest(offline=desired_offline))
                last_sent_offline = desired_offline
                if desired_offline:
                    log.info("📴 وضعیت: آفلاین")
                else:
                    log.debug("🟢 وضعیت آنلاین رفرش شد")
        except Exception as e:  # noqa: BLE001
            log.error(f"online_keeper: {e}")
        interval = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
        interval = max(MIN_ONLINE_INTERVAL, min(MAX_ONLINE_INTERVAL, interval))
        await asyncio.sleep(interval)


# ═════════════════════════════════════════════════════════════════
# ║               دستورات یوزربات (همه owner-only)                ║
# ═════════════════════════════════════════════════════════════════

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
    try:
        await client(UpdateStatusRequest(offline=not new))
    except Exception as e:  # noqa: BLE001
        log.error(f"UpdateStatusRequest: {e}")
    await event.edit(
        f"📡 **آنلاین دائم: {'روشن 🟢' if new else 'خاموش 🔴'}**\n"
        f"_بر اساس تنظیمات privacy تلگرامت نمایش داده میشه._"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}interval(?:\s+(\d+)([smSM]?))?$"))
@owner_only
async def cmd_interval(event):
    num = event.pattern_match.group(1)
    unit = (event.pattern_match.group(2) or "s").lower()
    if num is None:
        current = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
        await event.edit(
            "⏱ **بازه رفرش آنلاین**\n\n"
            f"📊 مقدار فعلی: `{current}s` (~{current // 60}m {current % 60}s)\n"
            f"🔢 محدوده مجاز: `{MIN_ONLINE_INTERVAL}` تا `{MAX_ONLINE_INTERVAL}` ثانیه\n\n"
            f"🛠 برای تغییر:\n"
            f"  `{CMD_PREFIX}interval 180`  → ۱۸۰ ثانیه\n"
            f"  `{CMD_PREFIX}interval 3m`   → ۳ دقیقه"
        )
        return
    value = int(num)
    if unit == "m":
        value *= 60
    if value < MIN_ONLINE_INTERVAL or value > MAX_ONLINE_INTERVAL:
        await event.edit(
            f"⚠️ مقدار باید بین `{MIN_ONLINE_INTERVAL}s` تا `{MAX_ONLINE_INTERVAL}s` باشه."
        )
        return
    config["online_refresh_interval"] = value
    save_config()
    await event.edit(
        "✅ **بازه رفرش آپدیت شد**\n"
        f"⏱ مقدار جدید: `{value}s` (~{value // 60}m {value % 60}s)"
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
    await event.edit(f"✅ **متن پاسخ خودکار آپدیت شد**\n\n📝 متن جدید:\n`{new_msg}`")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}afk(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_afk(event):
    reason = event.pattern_match.group(1)
    reason_l = reason.strip().lower() if reason else None

    if reason_l in {"off", "خاموش"}:
        config["autoreply_enabled"] = False
        replied_users.clear()
        save_config()
        await event.edit("✅ **AFK خاموش شد.**")
        return

    if reason and reason_l not in {"on", "روشن"}:
        config["autoreply_message"] = reason.strip()

    config["autoreply_enabled"] = True
    save_config()
    await event.edit(
        "💤 **AFK روشن شد.**\n"
        f"📝 پیام:\n`{config['autoreply_message']}`"
    )


# ═════════ دستورات AI ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ai(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_ai(event):
    arg = event.pattern_match.group(1)
    ready, err_msg = _ai_ready()
    if not ready:
        await event.edit(
            f"❌ **AI قابل استفاده نیست:** {err_msg}\n\n"
            "🔧 راه‌حل:\n"
            "  • اگه کتابخونه نیست:\n"
            "    `pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`\n"
            "  • اگه کلید نیست: `EMERGENT_LLM_KEY=...` رو در `.env` ست کن و ربات رو ری‌استارت کن."
        )
        return
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config.get("ai_enabled", False),
    )
    config["ai_enabled"] = new
    save_config()
    await event.edit(
        f"🤖 **دستیار AI: {'روشن 🟢' if new else 'خاموش 🔴'}**\n\n"
        f"📚 مدل: `{config['ai_model']}`\n"
        f"💬 در گروه‌ها: `{'روشن' if config.get('ai_groups_enabled') else 'خاموش'}`\n\n"
        "ℹ️ در چت خصوصی، وقتی پاسخ خودکار روشن باشه، AI پاسخ میده."
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aigroups(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_aigroups(event):
    arg = event.pattern_match.group(1)
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config.get("ai_groups_enabled", False),
    )
    config["ai_groups_enabled"] = new
    save_config()
    await event.edit(
        f"💬 **AI در گروه‌ها: {'روشن 🟢' if new else 'خاموش 🔴'}**\n\n"
        "ℹ️ در گروه فقط وقتی پاسخ میده که:\n"
        "  • کسی بهت reply بزنه\n"
        "  • کسی با @username منشنت کنه\n\n"
        "🧠 حافظه مکالمه گروه حفظ میشه (تا ریست کنی)."
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}personality(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_personality(event):
    new_text = event.pattern_match.group(1)
    if new_text is None:
        await event.edit(
            "🎭 **شخصیت فعلی دستیار:**\n\n"
            f"`{config['ai_personality']}`\n\n"
            f"برای تغییر: `{CMD_PREFIX}personality <متن جدید>`\n"
            f"برای ریست به پیش‌فرض: `{CMD_PREFIX}personality reset`"
        )
        return
    text = new_text.strip()
    if text.lower() in {"reset", "default", "پیشفرض"}:
        config["ai_personality"] = DEFAULT_AI_PERSONALITY
    else:
        config["ai_personality"] = text
    save_config()
    _reset_chat_sessions()
    await event.edit(
        "✅ **شخصیت دستیار آپدیت شد**\n\n"
        f"🎭 متن جدید:\n`{config['ai_personality']}`\n\n"
        "🔄 همه مکالمات قبلی ریست شدن."
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aimodel(?:\s+(\S+))?$"))
@owner_only
async def cmd_aimodel(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(
            f"📚 **مدل فعلی:** `{config['ai_model']}`\n\n"
            "🌟 مدل‌های پیشنهادی:\n"
            f"  `{CMD_PREFIX}aimodel gemini-3-flash-preview` ⚡ (پیش‌فرض)\n"
            f"  `{CMD_PREFIX}aimodel gemini-2.5-pro`\n"
            f"  `{CMD_PREFIX}aimodel claude-sonnet-4-5-20250929`\n"
            f"  `{CMD_PREFIX}aimodel gpt-5.2`\n"
            f"  `{CMD_PREFIX}aimodel gpt-4o-mini` (ارزون)"
        )
        return
    config["ai_model"] = arg
    save_config()
    _reset_chat_sessions()
    await event.edit(
        f"✅ **مدل AI آپدیت شد**\n\n"
        f"📚 مدل جدید: `{arg}`\n"
        f"🏢 ارائه‌دهنده: `{_infer_provider(arg)}`\n"
        "🔄 همه مکالمات ریست شدن."
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aireset$"))
@owner_only
async def cmd_aireset(event):
    count = len(_chat_sessions)
    _reset_chat_sessions()
    await event.edit(f"🔄 **حافظه AI ریست شد.** `{count}` session پاک شد.")


# ═════════ دستورات اطلاعاتی ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
@owner_only
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    interval = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
    ready, ai_err = _ai_ready()
    ai_status = "روشن 🟢" if config.get("ai_enabled") and ready else "خاموش 🔴"
    text = (
        "📊 **آمار و تنظیمات Bidar**\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📡 آنلاین دائم: `{'روشن 🟢' if config['online_enabled'] else 'خاموش 🔴'}`\n"
        f"🔄 بازه رفرش: `{interval}s` (~{interval // 60}m)\n"
        f"🤖 پاسخ خودکار: `{'روشن 🟢' if config['autoreply_enabled'] else 'خاموش 🔴'}`\n\n"
        f"🧠 **دستیار AI:** `{ai_status}`\n"
        f"  📚 مدل: `{config['ai_model']}`\n"
        f"  💬 در گروه‌ها: `{'روشن' if config.get('ai_groups_enabled') else 'خاموش'}`\n"
        f"  🗂 مکالمات فعال: `{len(_chat_sessions)}`\n\n"
        f"📨 پیام‌های دریافتی: `{stats['messages_received']}`\n"
        f"✉️ پاسخ‌های ارسالی: `{stats['replies_sent']}`\n"
        f"🤖 پاسخ‌های AI: `{stats['ai_replies']}`\n"
        f"⏳ Cooldown: `{config['autoreply_cooldown']}s`\n\n"
        f"📝 متن ثابت (fallback):\n`{config['autoreply_message']}`"
    )
    if not ready and config.get("ai_enabled"):
        text += f"\n\n⚠️ AI فعاله ولی غیرقابل استفاده: {ai_err}"
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}alive$"))
@owner_only
async def cmd_alive(event):
    uptime = time.time() - stats["start_time"]
    await event.edit(
        "✨ **Bidar زنده و آنلاینه** 🌙\n\n"
        f"⏱ آپ‌تایم: `{_fmt_uptime(uptime)}`\n"
        f"📡 آنلاین: `{'روشن' if config['online_enabled'] else 'خاموش'}`\n"
        f"🤖 پاسخ خودکار: `{'روشن' if config['autoreply_enabled'] else 'خاموش'}`\n"
        f"🧠 AI: `{'روشن' if config.get('ai_enabled') else 'خاموش'}`\n"
        f"🔖 نسخه: `v{VERSION}`"
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
        "📡 **وضعیت آنلاین**\n"
        f"  `{CMD_PREFIX}online on|off` — آنلاین دائم\n"
        f"  `{CMD_PREFIX}interval <s>` — بازه رفرش (پیش‌فرض ۲۴۰s)\n\n"
        "🤖 **پاسخ خودکار ثابت**\n"
        f"  `{CMD_PREFIX}reply on|off` — روشن/خاموش\n"
        f"  `{CMD_PREFIX}setmsg <متن>` — ویرایش متن\n"
        f"  `{CMD_PREFIX}afk [متن]` — میانبر AFK\n\n"
        "🧠 **دستیار AI**\n"
        f"  `{CMD_PREFIX}ai on|off` — روشن/خاموش AI\n"
        f"  `{CMD_PREFIX}aigroups on|off` — AI در گروه‌ها\n"
        f"  `{CMD_PREFIX}personality <متن>` — تنظیم شخصیت\n"
        f"  `{CMD_PREFIX}personality reset` — ریست به پیش‌فرض\n"
        f"  `{CMD_PREFIX}aimodel <مدل>` — تغییر مدل\n"
        f"  `{CMD_PREFIX}aireset` — پاک کردن حافظه مکالمات\n\n"
        "📊 **اطلاعات**\n"
        f"  `{CMD_PREFIX}alive` — زنده بودن\n"
        f"  `{CMD_PREFIX}ping` — تست تاخیر\n"
        f"  `{CMD_PREFIX}stats` — همه آمار\n"
        f"  `{CMD_PREFIX}id` — آیدی چت/کاربر\n\n"
        "🔧 **مدیریت**\n"
        f"  `{CMD_PREFIX}restart` — ری‌استارت\n"
        f"  `{CMD_PREFIX}help` — همین راهنما\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 همه دستورات owner-only  •  🔖 v{VERSION}"
    )
    await event.edit(text)


# ═════════════════════════════════════════════════════════════════
# ║              هندلر اصلی پیام‌های ورودی                         ║
# ═════════════════════════════════════════════════════════════════
@client.on(events.NewMessage(incoming=True))
async def handle_incoming(event):
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    if OWNER_ID is not None and sender.id == OWNER_ID:
        return

    if event.is_private:
        await _handle_private(event, sender)
    else:
        await _handle_group_or_channel(event, sender)


async def _handle_private(event, sender) -> None:
    stats["messages_received"] += 1

    if not config["autoreply_enabled"]:
        return

    now = time.time()
    last = replied_users.get(sender.id, 0)
    if now - last < config["autoreply_cooldown"]:
        return

    response_text: str | None = None

    # اگه AI روشنه، تلاش کن پاسخ هوشمند بگیری
    if config.get("ai_enabled"):
        ready, _ = _ai_ready()
        if ready:
            session_id = f"private_{sender.id}"
            response_text = await _ai_respond(session_id, event.raw_text or "")

    # fallback به متن ثابت
    if not response_text:
        response_text = config["autoreply_message"]

    try:
        await event.reply(response_text)
        replied_users[sender.id] = now
        stats["replies_sent"] += 1
        log.info(
            f"پاسخ به {getattr(sender, 'first_name', '?')} (id={sender.id}) — "
            f"{'AI' if config.get('ai_enabled') else 'static'}"
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"پاسخ ناموفق: {e}")


async def _handle_group_or_channel(event, sender) -> None:
    # در گروه‌ها فقط اگه AI + aigroups روشن باشه
    if not (config.get("ai_enabled") and config.get("ai_groups_enabled")):
        return

    ready, _ = _ai_ready()
    if not ready:
        return

    msg = event.message
    is_mention = bool(getattr(msg, "mentioned", False))
    # چک reply از چند مسیر (مطمئن‌ترین راه)
    reply_to_msg_id = (
        getattr(msg, "reply_to_msg_id", None)
        or getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)
    )
    is_reply = bool(event.is_reply or reply_to_msg_id)

    should_respond = False
    reason = ""

    # ۱) mention (شامل @username)
    if is_mention:
        should_respond = True
        reason = "mentioned"

    # ۲) reply به پیام مالک اکانت
    if not should_respond and is_reply:
        try:
            replied = await event.get_reply_message()
            if replied:
                # چک sender_id و از طرف خود کاربر بودن (out)
                replied_sender = replied.sender_id
                replied_out = getattr(replied, "out", False)
                if replied_sender == OWNER_ID or replied_out:
                    should_respond = True
                    reason = "reply_to_owner"
                else:
                    log.debug(
                        f"[group-reply] chat={event.chat_id} "
                        f"replied_sender={replied_sender} owner={OWNER_ID} out={replied_out}"
                    )
            else:
                log.debug(f"[group-reply] chat={event.chat_id} reply object is None")
        except Exception as e:  # noqa: BLE001
            log.warning(f"[group-reply] get_reply_message failed: {e}")

    log.info(
        f"[group-msg] chat={event.chat_id} from={sender.id} "
        f"mentioned={is_mention} is_reply={is_reply} "
        f"decision={'REPLY' if should_respond else 'SKIP'}({reason})"
    )

    if not should_respond:
        return

    # cooldown برای گروه
    chat_id = event.chat_id
    key = f"g_{chat_id}"
    now = time.time()
    last = replied_users.get(key, 0)
    if now - last < GROUP_REPLY_COOLDOWN:
        log.debug(f"[group-cooldown] chat={chat_id} skipping (within {GROUP_REPLY_COOLDOWN}s)")
        return

    session_id = f"group_{chat_id}"
    response_text = await _ai_respond(session_id, event.raw_text or "")
    if not response_text:
        return

    try:
        await event.reply(response_text)
        replied_users[key] = now
        stats["replies_sent"] += 1
        log.info(f"پاسخ گروه {chat_id} با AI ({reason})")
    except Exception as e:  # noqa: BLE001
        log.error(f"پاسخ گروه ناموفق: {e}")


# ═════════════════════════════════════════════════════════════════
# ║                            اجرا                               ║
# ═════════════════════════════════════════════════════════════════
async def main():
    global OWNER_ID
    log.info("در حال اتصال به تلگرام...")
    await client.start(phone=PHONE)
    me = await client.get_me()
    OWNER_ID = me.id
    log.info(f"✅ لاگین شد: {me.first_name} (@{me.username}) — id={me.id}")

    ready, err_msg = _ai_ready()
    ai_info = f"🟢 آماده ({config['ai_model']})" if ready else f"🔴 {err_msg}"

    print(
        "\n🌙 Bidar v" + VERSION + " فعال شد!\n"
        f"   نام:     {me.first_name}\n"
        f"   یوزرنیم: @{me.username}\n"
        f"   آیدی:    {me.id}\n"
        f"   دستورات: {CMD_PREFIX}help\n"
        f"   آنلاین: {'🟢' if config['online_enabled'] else '🔴'}  "
        f"پاسخ خودکار: {'🟢' if config['autoreply_enabled'] else '🔴'}  "
        f"AI: {'🟢' if config.get('ai_enabled') else '🔴'}\n"
        f"   AI status: {ai_info}\n"
    )
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
