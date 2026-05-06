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
import base64
import io
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateStatusRequest

# Optional: AI integration via Emergent Universal Key
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # type: ignore
    AI_LIB_OK = True
except ImportError:  # کتابخونه نصب نباشه، AI غیرفعال میشه
    AI_LIB_OK = False
    LlmChat = None  # type: ignore
    UserMessage = None  # type: ignore
    ImageContent = None  # type: ignore

# ───────────────────────── پیکربندی پایه (.env) ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.5.0"

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "").strip()

DEFAULT_AUTOREPLY = os.environ.get(
    "AFK_MESSAGE",
    "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏",
)
DEFAULT_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))
DEFAULT_ONLINE_INTERVAL = 240
MIN_ONLINE_INTERVAL = 30
MAX_ONLINE_INTERVAL = 300
DEFAULT_GROUP_COOLDOWN = 0  # ثانیه — 0 یعنی بدون تاخیر (به همه replyها جواب میده)

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
    "group_cooldown": DEFAULT_GROUP_COOLDOWN,
    # Translation
    "translate_target": "fa",  # زبان پیش‌فرض ترجمه
    # Image generation
    "image_model": "gemini-3.1-flash-image-preview",
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


# ─────────── ترجمه و تولید تصویر (یکبار-مصرف، بدون حافظه) ───────────
async def _translate_text(text: str, target_lang: str) -> str | None:
    """ترجمه یک‌متنی بدون حافظه (هر بار session جدید)."""
    ready, _ = _ai_ready()
    if not ready or not text.strip():
        return None
    system_msg = (
        f"You are a professional translator. Translate the user's input to '{target_lang}'. "
        "Output ONLY the translated text — no explanations, no quotes, no language labels, "
        "no extra context. Preserve formatting, emojis, links, and punctuation. "
        "If the source is already in the target language, refine it slightly. "
        "If the input contains commands or technical terms, keep them intact."
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"translate-{time.time_ns()}",
            system_message=system_msg,
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        resp = await chat.send_message(UserMessage(text=text))
        return str(resp).strip()
    except Exception as e:  # noqa: BLE001
        log.error(f"Translate error: {e}")
        return None


async def _generate_image(prompt: str) -> bytes | None:
    """تولید تصویر از prompt متنی. خروجی: bytes تصویر یا None در صورت خطا."""
    ready, _ = _ai_ready()
    if not ready or not prompt.strip():
        return None
    model_name = config.get("image_model", "gemini-3.1-flash-image-preview")
    try:
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"image-{time.time_ns()}",
                system_message="You are an expert image generator. Create high-quality, detailed images based on the user's prompt.",
            )
            .with_model("gemini", model_name)
            .with_params(modalities=["image", "text"])
        )
        _text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
        if not images:
            log.warning("Image gen: no images returned")
            return None
        return base64.b64decode(images[0]["data"])
    except Exception as e:  # noqa: BLE001
        log.error(f"Image gen error: {e}")
        return None


async def _edit_image(image_bytes: bytes, edit_prompt: str) -> bytes | None:
    """ویرایش تصویر موجود با prompt. خروجی: bytes تصویر ویرایش‌شده یا None."""
    ready, _ = _ai_ready()
    if not ready or not edit_prompt.strip() or not image_bytes:
        return None
    model_name = config.get("image_model", "gemini-3.1-flash-image-preview")
    try:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"imgedit-{time.time_ns()}",
                system_message="You are an expert image editor. Edit the given reference image based on the user's instructions while preserving the main subject's identity unless told otherwise.",
            )
            .with_model("gemini", model_name)
            .with_params(modalities=["image", "text"])
        )
        msg = UserMessage(
            text=edit_prompt,
            file_contents=[ImageContent(image_b64)],
        )
        _text, images = await chat.send_message_multimodal_response(msg)
        if not images:
            log.warning("Image edit: no images returned")
            return None
        return base64.b64decode(images[0]["data"])
    except Exception as e:  # noqa: BLE001
        log.error(f"Image edit error: {e}")
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


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}groupcd(?:\s+(\d+))?$"))
@owner_only
async def cmd_groupcd(event):
    """تنظیم cooldown پاسخ AI در گروه (ثانیه). 0 = بدون محدودیت."""
    arg = event.pattern_match.group(1)
    if arg is None:
        current = int(config.get("group_cooldown", DEFAULT_GROUP_COOLDOWN))
        await event.edit(
            "⏳ **Cooldown پاسخ AI در گروه**\n\n"
            f"📊 مقدار فعلی: `{current}s` "
            f"{'(بدون محدودیت)' if current == 0 else f'(~{current // 60}m {current % 60}s در هر نفر)'}\n\n"
            "🛠 برای تغییر:\n"
            f"  `{CMD_PREFIX}groupcd 0`   → بدون محدودیت (پیش‌فرض)\n"
            f"  `{CMD_PREFIX}groupcd 10`  → ۱۰ ثانیه بین پاسخ‌ها به هر کاربر\n"
            f"  `{CMD_PREFIX}groupcd 60`  → ۱ دقیقه\n\n"
            "ℹ️ cooldown به ازای هر **کاربر** در گروه اعمال میشه، نه کل گروه."
        )
        return
    value = int(arg)
    if value < 0 or value > 3600:
        await event.edit("⚠️ مقدار باید بین `0` تا `3600` ثانیه باشه.")
        return
    config["group_cooldown"] = value
    save_config()
    state = "بدون محدودیت ⚡" if value == 0 else f"`{value}s` در هر کاربر"
    await event.edit(f"✅ **Group Cooldown آپدیت شد**\n⏳ مقدار جدید: {state}")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aireset$"))
@owner_only
async def cmd_aireset(event):
    count = len(_chat_sessions)
    _reset_chat_sessions()
    await event.edit(f"🔄 **حافظه AI ریست شد.** `{count}` session پاک شد.")


# ═════════ دستور تولید پاسخ دستی با AI ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}r(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_generate_reply(event):
    """
    AI بر اساس ۱۰ پیام اخیر این چت، یه پاسخ طبیعی می‌سازه
    و پیام دستور رو به همون پاسخ edit می‌کنه.

    استفاده:
      .r           → پاسخ بر اساس context
      .r <hint>    → پاسخ با راهنمایی (مثلاً "کوتاه و مودب" یا "شوخ")
      reply + .r   → اولویت با پیام ریپلای شده
    """
    ready, err = _ai_ready()
    if not ready:
        await event.edit(f"❌ AI آماده نیست: {err}")
        return

    hint = event.pattern_match.group(1)
    await event.edit("🤔 ...")

    # ───── جمع‌آوری context از چت فعلی ─────
    context_lines: list[str] = []
    try:
        # iter_messages به ترتیب نزولی (جدید → قدیم)
        async for msg in client.iter_messages(event.chat_id, limit=20):
            if msg.id == event.id:
                continue  # رد پیام دستور خود .r
            text = (msg.raw_text or msg.text or "").strip()
            if not text:
                continue
            if text.startswith(CMD_PREFIX):
                continue  # رد دستورات
            # نام فرستنده
            if msg.sender_id == OWNER_ID:
                name = "You"
            else:
                try:
                    sender = await msg.get_sender()
                    name = getattr(sender, "first_name", None) or "User"
                except Exception:  # noqa: BLE001
                    name = "User"
            context_lines.append(f"{name}: {text[:400]}")
            if len(context_lines) >= 10:
                break
        context_lines.reverse()  # قدیم → جدید
    except Exception as e:  # noqa: BLE001
        log.warning(f"cmd_r: failed to fetch context: {e}")

    # ───── پیام هدف (اگه ریپلای باشه) ─────
    target_text: str | None = None
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
            if replied:
                t = (replied.raw_text or replied.text or "").strip()
                if t:
                    target_text = t[:500]
        except Exception:  # noqa: BLE001
            pass

    # ───── ساخت prompt ─────
    context_str = "\n".join(context_lines) if context_lines else "(no recent context)"
    chat_type = "private chat" if event.is_private else "group chat"

    system_msg = (
        "You are replying as 'You' in a real Telegram conversation. "
        f"This is a {chat_type}. "
        "Generate a natural, contextually-appropriate message that 'You' would send right now. "
        "Match the tone, style, and language of the conversation (if it's Persian, reply in Persian; "
        "if English, reply in English; etc). "
        "Keep it short and natural — like how a real person texts. "
        "Do NOT introduce yourself as AI, bot, or assistant. "
        "Output ONLY the message text — no quotes, no labels, no explanations."
    )

    parts = [f"Recent conversation:\n{context_str}"]
    if target_text:
        parts.append(f"\n(The focus is this specific message you should address:)\n{target_text}")
    if hint:
        parts.append(f"\n(Additional instruction for your reply: {hint})")
    parts.append("\nNow write the reply message:")
    user_prompt = "\n".join(parts)

    # ───── فراخوانی AI ─────
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"genreply-{time.time_ns()}",
            system_message=system_msg,
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        resp = await chat.send_message(UserMessage(text=user_prompt))
        reply_text = str(resp).strip()
        # حذف کوتیشن‌های اضافی که بعضی مدل‌ها اضافه می‌کنن
        if (reply_text.startswith('"') and reply_text.endswith('"')) or \
           (reply_text.startswith("«") and reply_text.endswith("»")):
            reply_text = reply_text[1:-1].strip()
        if not reply_text:
            await event.edit("❌ AI پاسخی تولید نکرد. دوباره امتحان کن.")
            return
        stats["ai_replies"] += 1
        await event.edit(reply_text)
        log.info(f"[.r] generated in chat={event.chat_id} len={len(reply_text)}")
    except Exception as e:  # noqa: BLE001
        log.error(f"cmd_r error: {e}")
        await event.edit(f"❌ خطا در تولید پاسخ: {e}")


# ═════════ دستورات ترجمه ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}lang(?:\s+([a-zA-Z\-]+))?$"))
@owner_only
async def cmd_lang(event):
    """تنظیم زبان پیش‌فرض ترجمه."""
    arg = event.pattern_match.group(1)
    if arg is None:
        current = config.get("translate_target", "fa")
        await event.edit(
            f"🌐 **زبان پیش‌فرض ترجمه:** `{current}`\n\n"
            f"🛠 برای تغییر:\n"
            f"  `{CMD_PREFIX}lang fa` — فارسی\n"
            f"  `{CMD_PREFIX}lang en` — انگلیسی\n"
            f"  `{CMD_PREFIX}lang ar` — عربی\n"
            f"  `{CMD_PREFIX}lang fr` — فرانسوی\n"
            f"  `{CMD_PREFIX}lang de`, `es`, `tr`, `ru`, `zh` و ...\n\n"
            f"این زبان برای دستور `{CMD_PREFIX}tl` استفاده میشه."
        )
        return
    config["translate_target"] = arg.lower()
    save_config()
    await event.edit(f"✅ زبان پیش‌فرض ترجمه به `{arg.lower()}` تنظیم شد.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}tl(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_translate(event):
    """ترجمه به زبان پیش‌فرض. اگه ریپلای باشه، پیام ریپلای شده ترجمه میشه."""
    target = config.get("translate_target", "fa")
    text_arg = event.pattern_match.group(1)

    if text_arg:
        source_text = text_arg.strip()
    elif event.is_reply:
        try:
            replied = await event.get_reply_message()
            if replied and (replied.raw_text or replied.text):
                source_text = replied.raw_text or replied.text or ""
            else:
                await event.edit("❌ پیام ریپلای شده متن نداره.")
                return
        except Exception as e:  # noqa: BLE001
            await event.edit(f"❌ خطا در دریافت پیام ریپلای: {e}")
            return
    else:
        await event.edit(
            f"🌐 **استفاده از ترجمه:**\n\n"
            f"  `{CMD_PREFIX}tl <متن>` — ترجمه متن\n"
            f"  ریپلای + `{CMD_PREFIX}tl` — ترجمه پیام ریپلای شده\n"
            f"  `{CMD_PREFIX}lang <code>` — تغییر زبان مقصد\n\n"
            f"🎯 زبان فعلی: `{target}`"
        )
        return

    msg = await event.edit("🌐 در حال ترجمه...")
    translated = await _translate_text(source_text, target)
    if translated:
        await msg.edit(f"🌐 **ترجمه ({target}):**\n\n{translated}")
    else:
        await msg.edit("❌ ترجمه ناموفق بود. AI رو چک کن.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}to\s+([a-zA-Z\-]+)\s+([\s\S]+)$"))
@owner_only
async def cmd_to(event):
    """متن رو به زبان مشخص ترجمه می‌کنه و پیام رو edit می‌کنه (نه reply)."""
    target = event.pattern_match.group(1).lower()
    text = event.pattern_match.group(2).strip()

    msg = await event.edit("✏️ در حال ترجمه...")
    translated = await _translate_text(text, target)
    if translated:
        # فقط متن ترجمه‌شده رو نشون بده، بدون توضیح اضافی
        await msg.edit(translated)
    else:
        await msg.edit(f"{text}\n\n❌ ترجمه ناموفق بود.")


# ═════════ دستور تولید تصویر ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}img(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_image(event):
    """تولید تصویر با Gemini Nano Banana."""
    prompt = event.pattern_match.group(1)
    if not prompt or not prompt.strip():
        await event.edit(
            f"🎨 **تولید تصویر**\n\n"
            f"  `{CMD_PREFIX}img <توضیح تصویر>`\n\n"
            f"📝 مثال:\n"
            f"  `{CMD_PREFIX}img a fluffy cat astronaut on Mars`\n"
            f"  `{CMD_PREFIX}img نقاشی مینیمال از کوه‌های دماوند هنگام غروب`\n\n"
            f"🎯 مدل فعلی: `{config.get('image_model', 'gemini-3.1-flash-image-preview')}`"
        )
        return

    prompt = prompt.strip()
    msg = await event.edit(f"🎨 در حال تولید تصویر...\n_{prompt[:100]}_")

    img_bytes = await _generate_image(prompt)
    if not img_bytes:
        await msg.edit(
            "❌ تولید تصویر ناموفق بود.\n"
            "بررسی کن: AI روشن باشه، EMERGENT_LLM_KEY ست شده باشه، prompt مناسب باشه."
        )
        return

    # ذخیره موقت در فایل و ارسال
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_bytes)
            tmp = f.name

        await client.send_file(
            event.chat_id,
            tmp,
            caption=f"🎨 {prompt[:1000]}",
            reply_to=event.reply_to_msg_id,
        )
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.error(f"Send image: {e}")
        await msg.edit(f"❌ ارسال تصویر ناموفق: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}imgmodel(?:\s+(\S+))?$"))
@owner_only
async def cmd_imgmodel(event):
    """تغییر مدل تولید تصویر."""
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(
            f"🎨 **مدل تولید تصویر:** `{config.get('image_model', 'gemini-3.1-flash-image-preview')}`\n\n"
            "🌟 مدل‌های موجود:\n"
            f"  `{CMD_PREFIX}imgmodel gemini-3.1-flash-image-preview` ⚡ (پیش‌فرض، Nano Banana)\n"
            f"  `{CMD_PREFIX}imgmodel gemini-3-pro-image-preview` 🔥 (Pro، کیفیت بالاتر)"
        )
        return
    config["image_model"] = arg
    save_config()
    await event.edit(f"✅ مدل تولید تصویر به `{arg}` تنظیم شد.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}imgedit(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_imgedit(event):
    """ویرایش تصویر با AI. باید روی یه پیام عکس‌دار ریپلای بزنی."""
    prompt = event.pattern_match.group(1)
    if not prompt or not prompt.strip():
        await event.edit(
            f"🖼 **ویرایش تصویر**\n\n"
            f"🔧 طرز استفاده:\n"
            f"۱. روی یه پیام **عکس‌دار** ریپلای بزن\n"
            f"۲. تایپ کن: `{CMD_PREFIX}imgedit <توضیح تغییر>`\n\n"
            f"📝 مثال:\n"
            f"  `{CMD_PREFIX}imgedit پس‌زمینه رو شب پر ستاره بزن`\n"
            f"  `{CMD_PREFIX}imgedit کلاه قرمز روی سرش بذار`\n"
            f"  `{CMD_PREFIX}imgedit make it black and white vintage style`\n"
            f"  `{CMD_PREFIX}imgedit add a rainbow in the sky`"
        )
        return

    if not event.is_reply:
        await event.edit("❌ باید روی یه پیام **عکس‌دار** ریپلای بزنی.")
        return

    prompt = prompt.strip()
    msg = await event.edit(f"🖼 در حال ویرایش تصویر...\n_{prompt[:100]}_")

    try:
        replied = await event.get_reply_message()
    except Exception as e:  # noqa: BLE001
        await msg.edit(f"❌ خطا در دریافت پیام ریپلای: {e}")
        return

    if not replied or not replied.media:
        await msg.edit("❌ پیام ریپلای شده عکس نداره.")
        return

    # دانلود تصویر از تلگرام به صورت bytes
    try:
        img_bytes = await client.download_media(replied, file=bytes)
    except Exception as e:  # noqa: BLE001
        await msg.edit(f"❌ خطا در دانلود تصویر: {e}")
        return

    if not img_bytes or not isinstance(img_bytes, bytes):
        await msg.edit("❌ تصویر معتبر دریافت نشد.")
        return

    # ویرایش با AI
    edited_bytes = await _edit_image(img_bytes, prompt)
    if not edited_bytes:
        await msg.edit(
            "❌ ویرایش تصویر ناموفق بود.\n"
            "احتمالاً مدل نتونسته prompt رو پیاده کنه — متن ساده‌تر امتحان کن."
        )
        return

    # ذخیره موقت و ارسال
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(edited_bytes)
            tmp = f.name

        await client.send_file(
            event.chat_id,
            tmp,
            caption=f"🖼 **ویرایش‌شده:** {prompt[:900]}",
            reply_to=replied.id,
        )
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.error(f"Send edited image: {e}")
        await msg.edit(f"❌ ارسال تصویر ویرایش‌شده ناموفق: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


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
        f"  ⏳ Group cooldown: `{config.get('group_cooldown', 0)}s`"
        f"{' (بدون محدودیت)' if config.get('group_cooldown', 0) == 0 else ''}\n"
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
        f"  `{CMD_PREFIX}groupcd <s>` — cooldown گروه (۰=بدون محدودیت)\n"
        f"  `{CMD_PREFIX}aireset` — پاک کردن حافظه مکالمات\n"
        f"  `{CMD_PREFIX}r [hint]` — **تولید پاسخ دستی** با AI بر اساس چت فعلی\n\n"
        "🌐 **ترجمه**\n"
        f"  `{CMD_PREFIX}lang <code>` — تنظیم زبان پیش‌فرض (fa, en, ar, ...)\n"
        f"  `{CMD_PREFIX}tl <متن>` — ترجمه به زبان پیش‌فرض\n"
        f"  ریپلای + `{CMD_PREFIX}tl` — ترجمه پیام ریپلای شده\n"
        f"  `{CMD_PREFIX}to <code> <متن>` — متن رو ادیت می‌کنه به زبان دیگه\n"
        f"     مثال: `{CMD_PREFIX}to en سلام چطوری`\n\n"
        "🎨 **تولید تصویر**\n"
        f"  `{CMD_PREFIX}img <توضیح>` — تولید تصویر با Nano Banana\n"
        f"  `{CMD_PREFIX}imgedit <توضیح>` — ویرایش عکس (روی عکس reply بزن)\n"
        f"  `{CMD_PREFIX}imgmodel <model>` — تغییر مدل تصویر\n\n"
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

    # cooldown برای گروه (فقط اگه > 0 باشه اعمال میشه)
    chat_id = event.chat_id
    cooldown = int(config.get("group_cooldown", DEFAULT_GROUP_COOLDOWN))
    if cooldown > 0:
        key = f"g_{chat_id}_{sender.id}"  # per-user instead of per-chat
        now = time.time()
        last = replied_users.get(key, 0)
        if now - last < cooldown:
            log.debug(f"[group-cooldown] chat={chat_id} user={sender.id} skipping (within {cooldown}s)")
            return
        replied_users[key] = now

    session_id = f"group_{event.chat_id}"
    response_text = await _ai_respond(session_id, event.raw_text or "")
    if not response_text:
        return

    try:
        await event.reply(response_text)
        stats["replies_sent"] += 1
        log.info(f"پاسخ گروه {event.chat_id} با AI ({reason})")
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
