"""
Bidar — Bilingual Telegram Userbot with AI Assistant 🌙🤖
============================================================

Features:
  • Always-online (UpdateStatusRequest periodic)
  • Static & AI-powered auto-reply with per-chat context
  • Image generation, editing, OCR via Gemini
  • Translation (.tl, .to)
  • Bilingual UI (English + Persian) — switchable at runtime
  • Owner-only command lock with double safety check
  • Persistent JSON config

See `.help` for full command list.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateStatusRequest

# Optional: AI integration via Emergent Universal Key
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # type: ignore
    AI_LIB_OK = True
except ImportError:
    AI_LIB_OK = False
    LlmChat = None  # type: ignore
    UserMessage = None  # type: ignore
    ImageContent = None  # type: ignore

# ────────────────────────── Base config (.env) ──────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.7.0"

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "").strip()

DEFAULT_AUTOREPLY = os.environ.get(
    "AFK_MESSAGE",
    "Hi 👋 I'm not available right now, I'll get back to you soon 🙏",
)
DEFAULT_COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "1800"))
DEFAULT_ONLINE_INTERVAL = 240
MIN_ONLINE_INTERVAL = 30
MAX_ONLINE_INTERVAL = 300
DEFAULT_GROUP_COOLDOWN = 0

DEFAULT_AI_PERSONALITY = (
    "You are replying on behalf of the account owner. The owner is currently unavailable. "
    "Respond naturally, briefly, and politely as if you are the account owner — do NOT introduce "
    "yourself as an AI, bot, or assistant. If asked when you'll be back, say 'soon' or 'I'll let you know'. "
    "Match the language used by the sender (Persian, English, Arabic, etc). "
    "In group chats, consider the conversation context."
)

# ───────────────────────── Persistent config (JSON) ─────────────────────────
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
    "translate_target": "fa",
    # Image generation
    "image_model": "gemini-3.1-flash-image-preview",
    # UI language
    "bot_lang": "en",  # "en" or "fa"
}

config: dict = dict(_DEFAULT_CONFIG)


def load_config() -> None:
    global config
    base = dict(_DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            base.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning(f"Config read failed; using defaults: {e}")
    config = base


def save_config() -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Config save failed: {e}")


# ────────────── Runtime state (in-memory) ──────────────
OWNER_ID: int | None = None
replied_users: dict[int | str, float] = {}
stats = {
    "start_time": time.time(),
    "replies_sent": 0,
    "messages_received": 0,
    "ai_replies": 0,
}
_chat_sessions: dict[str, object] = {}

# ───────────────────────── Logging ─────────────────────────
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

# ───────────────────────── Client ─────────────────────────
client = TelegramClient(str(BASE_DIR / SESSION_NAME), API_ID, API_HASH)


# ═══════════════════════════════════════════════════════════════════
# ║                        I18N (Bilingual UI)                       ║
# ═══════════════════════════════════════════════════════════════════
I18N = {
    # Common
    "on": {"en": "ON 🟢", "fa": "روشن 🟢"},
    "off": {"en": "OFF 🔴", "fa": "خاموش 🔴"},
    "yes": {"en": "Yes", "fa": "بله"},
    "no": {"en": "No", "fa": "خیر"},
    "no_limit": {"en": "(no limit)", "fa": "(بدون محدودیت)"},

    # Online
    "online_set": {
        "en": "📡 **Always Online: {state}**\n_Visibility follows your Telegram privacy settings._",
        "fa": "📡 **آنلاین دائم: {state}**\n_بر اساس تنظیمات privacy تلگرامت نمایش داده میشه._",
    },

    # Interval
    "interval_show": {
        "en": "⏱ **Online Refresh Interval**\n\n📊 Current: `{cur}s` (~{m}m {s}s)\n🔢 Allowed range: `{mn}` to `{mx}` seconds\n\n🛠 To change:\n  `{p}interval 180`  → 180 seconds\n  `{p}interval 3m`   → 3 minutes",
        "fa": "⏱ **بازه رفرش آنلاین**\n\n📊 مقدار فعلی: `{cur}s` (~{m}m {s}s)\n🔢 محدوده مجاز: `{mn}` تا `{mx}` ثانیه\n\n🛠 برای تغییر:\n  `{p}interval 180`  → ۱۸۰ ثانیه\n  `{p}interval 3m`   → ۳ دقیقه",
    },
    "interval_out_of_range": {
        "en": "⚠️ Value must be between `{mn}s` and `{mx}s`.",
        "fa": "⚠️ مقدار باید بین `{mn}s` تا `{mx}s` باشه.",
    },
    "interval_updated": {
        "en": "✅ **Refresh interval updated**\n⏱ New value: `{v}s` (~{m}m {s}s)",
        "fa": "✅ **بازه رفرش آپدیت شد**\n⏱ مقدار جدید: `{v}s` (~{m}m {s}s)",
    },

    # Auto-reply
    "reply_set": {
        "en": "🤖 **Auto-reply: {state}**\n📝 Current message:\n`{msg}`",
        "fa": "🤖 **پاسخ خودکار: {state}**\n📝 متن فعلی:\n`{msg}`",
    },
    "setmsg_done": {
        "en": "✅ **Auto-reply message updated**\n\n📝 New message:\n`{msg}`",
        "fa": "✅ **متن پاسخ خودکار آپدیت شد**\n\n📝 متن جدید:\n`{msg}`",
    },
    "afk_off": {
        "en": "✅ **AFK turned off.**",
        "fa": "✅ **AFK خاموش شد.**",
    },
    "afk_on": {
        "en": "💤 **AFK turned on.**\n📝 Message:\n`{msg}`",
        "fa": "💤 **AFK روشن شد.**\n📝 پیام:\n`{msg}`",
    },

    # AI
    "ai_not_ready": {
        "en": "❌ **AI not available:** {err}\n\n🔧 Solution:\n  • If library missing:\n    `pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`\n  • If key missing: set `EMERGENT_LLM_KEY=...` in `.env` and restart the bot.",
        "fa": "❌ **AI قابل استفاده نیست:** {err}\n\n🔧 راه‌حل:\n  • اگه کتابخونه نیست:\n    `pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`\n  • اگه کلید نیست: `EMERGENT_LLM_KEY=...` رو در `.env` ست کن و ربات رو ری‌استارت کن.",
    },
    "ai_set": {
        "en": "🤖 **AI Assistant: {state}**\n\n📚 Model: `{model}`\n💬 In groups: `{groups}`\n\nℹ️ In private chats, AI responds when auto-reply is on.",
        "fa": "🤖 **دستیار AI: {state}**\n\n📚 مدل: `{model}`\n💬 در گروه‌ها: `{groups}`\n\nℹ️ در چت خصوصی، وقتی پاسخ خودکار روشن باشه، AI پاسخ میده.",
    },
    "aigroups_set": {
        "en": "💬 **AI in groups: {state}**\n\nℹ️ In groups, AI only replies when:\n  • Someone replies to your message\n  • Someone mentions you with @username\n\n🧠 Group conversation memory is preserved (until reset).",
        "fa": "💬 **AI در گروه‌ها: {state}**\n\nℹ️ در گروه فقط وقتی پاسخ میده که:\n  • کسی بهت reply بزنه\n  • کسی با @username منشنت کنه\n\n🧠 حافظه مکالمه گروه حفظ میشه (تا ریست کنی).",
    },
    "personality_show": {
        "en": "🎭 **Current AI Personality:**\n\n`{p}`\n\nTo change: `{prefix}personality <new text>`\nTo reset: `{prefix}personality reset`",
        "fa": "🎭 **شخصیت فعلی دستیار:**\n\n`{p}`\n\nبرای تغییر: `{prefix}personality <متن جدید>`\nبرای ریست به پیش‌فرض: `{prefix}personality reset`",
    },
    "personality_updated": {
        "en": "✅ **AI personality updated**\n\n🎭 New text:\n`{p}`\n\n🔄 All previous conversations have been reset.",
        "fa": "✅ **شخصیت دستیار آپدیت شد**\n\n🎭 متن جدید:\n`{p}`\n\n🔄 همه مکالمات قبلی ریست شدن.",
    },
    "aimodel_show": {
        "en": "📚 **Current model:** `{m}`\n\n🌟 Recommended models:\n  `{p}aimodel gemini-3-flash-preview` ⚡ (default)\n  `{p}aimodel gemini-2.5-pro`\n  `{p}aimodel claude-sonnet-4-5-20250929`\n  `{p}aimodel gpt-5.2`\n  `{p}aimodel gpt-4o-mini` (cheap)",
        "fa": "📚 **مدل فعلی:** `{m}`\n\n🌟 مدل‌های پیشنهادی:\n  `{p}aimodel gemini-3-flash-preview` ⚡ (پیش‌فرض)\n  `{p}aimodel gemini-2.5-pro`\n  `{p}aimodel claude-sonnet-4-5-20250929`\n  `{p}aimodel gpt-5.2`\n  `{p}aimodel gpt-4o-mini` (ارزون)",
    },
    "aimodel_updated": {
        "en": "✅ **AI model updated**\n\n📚 New model: `{m}`\n🏢 Provider: `{prov}`\n🔄 All conversations reset.",
        "fa": "✅ **مدل AI آپدیت شد**\n\n📚 مدل جدید: `{m}`\n🏢 ارائه‌دهنده: `{prov}`\n🔄 همه مکالمات ریست شدن.",
    },
    "aireset_done": {
        "en": "🔄 **AI memory reset.** `{n}` session(s) cleared.",
        "fa": "🔄 **حافظه AI ریست شد.** `{n}` session پاک شد.",
    },
    "groupcd_show": {
        "en": "⏳ **Group AI cooldown**\n\n📊 Current: `{cur}s` {note}\n\n🛠 To change:\n  `{p}groupcd 0`   → no limit (default)\n  `{p}groupcd 10`  → 10 seconds per user\n  `{p}groupcd 60`  → 1 minute\n\nℹ️ Cooldown is applied **per user**, not the whole group.",
        "fa": "⏳ **Cooldown پاسخ AI در گروه**\n\n📊 مقدار فعلی: `{cur}s` {note}\n\n🛠 برای تغییر:\n  `{p}groupcd 0`   → بدون محدودیت (پیش‌فرض)\n  `{p}groupcd 10`  → ۱۰ ثانیه بین پاسخ‌ها به هر کاربر\n  `{p}groupcd 60`  → ۱ دقیقه\n\nℹ️ cooldown به ازای هر **کاربر** در گروه اعمال میشه، نه کل گروه.",
    },
    "groupcd_invalid": {
        "en": "⚠️ Value must be between `0` and `3600` seconds.",
        "fa": "⚠️ مقدار باید بین `0` تا `3600` ثانیه باشه.",
    },
    "groupcd_updated": {
        "en": "✅ **Group cooldown updated**\n⏳ New value: {v}",
        "fa": "✅ **Group Cooldown آپدیت شد**\n⏳ مقدار جدید: {v}",
    },

    # .r
    "r_thinking": {"en": "🤔 ...", "fa": "🤔 ..."},
    "r_no_response": {
        "en": "❌ AI didn't generate a response. Try again.",
        "fa": "❌ AI پاسخی تولید نکرد. دوباره امتحان کن.",
    },
    "r_error": {"en": "❌ Error generating reply: {e}", "fa": "❌ خطا در تولید پاسخ: {e}"},

    # Translation
    "lang_show": {
        "en": "🌐 **Default translation language:** `{l}`\n\n🛠 To change:\n  `{p}lang fa` — Persian\n  `{p}lang en` — English\n  `{p}lang ar` — Arabic\n  `{p}lang fr`, `de`, `es`, `tr`, `ru`, `zh`, `ja`, ...\n\nThis is used by `{p}tl`.",
        "fa": "🌐 **زبان پیش‌فرض ترجمه:** `{l}`\n\n🛠 برای تغییر:\n  `{p}lang fa` — فارسی\n  `{p}lang en` — انگلیسی\n  `{p}lang ar` — عربی\n  `{p}lang fr`, `de`, `es`, `tr`, `ru`, `zh`, `ja` و ...\n\nاین زبان برای دستور `{p}tl` استفاده میشه.",
    },
    "lang_set": {"en": "✅ Default translation language set to `{l}`.", "fa": "✅ زبان پیش‌فرض ترجمه به `{l}` تنظیم شد."},
    "tl_no_text": {"en": "❌ The replied message has no text.", "fa": "❌ پیام ریپلای شده متن نداره."},
    "tl_reply_error": {"en": "❌ Error fetching replied message: {e}", "fa": "❌ خطا در دریافت پیام ریپلای: {e}"},
    "tl_usage": {
        "en": "🌐 **Translation usage:**\n\n  `{p}tl <text>` — translate text\n  reply + `{p}tl` — translate the replied message\n  `{p}lang <code>` — change default target\n\n🎯 Current target: `{t}`",
        "fa": "🌐 **استفاده از ترجمه:**\n\n  `{p}tl <متن>` — ترجمه متن\n  ریپلای + `{p}tl` — ترجمه پیام ریپلای شده\n  `{p}lang <code>` — تغییر زبان مقصد\n\n🎯 زبان فعلی: `{t}`",
    },
    "tl_processing": {"en": "🌐 Translating...", "fa": "🌐 در حال ترجمه..."},
    "tl_result": {"en": "🌐 **Translation ({t}):**\n\n{txt}", "fa": "🌐 **ترجمه ({t}):**\n\n{txt}"},
    "tl_failed": {"en": "❌ Translation failed. Check AI status.", "fa": "❌ ترجمه ناموفق بود. AI رو چک کن."},
    "to_processing": {"en": "✏️ Translating...", "fa": "✏️ در حال ترجمه..."},
    "to_failed": {"en": "{txt}\n\n❌ Translation failed.", "fa": "{txt}\n\n❌ ترجمه ناموفق بود."},

    # Image
    "img_usage": {
        "en": "🎨 **Image generation**\n\n  `{p}img <description>`\n\n📝 Examples:\n  `{p}img a fluffy cat astronaut on Mars`\n  `{p}img minimalist watercolor of mountains at sunset`\n\n🎯 Current model: `{m}`",
        "fa": "🎨 **تولید تصویر**\n\n  `{p}img <توضیح تصویر>`\n\n📝 مثال:\n  `{p}img a fluffy cat astronaut on Mars`\n  `{p}img نقاشی مینیمال از کوه‌های دماوند هنگام غروب`\n\n🎯 مدل فعلی: `{m}`",
    },
    "img_processing": {"en": "🎨 Generating image...\n_{p}_", "fa": "🎨 در حال تولید تصویر...\n_{p}_"},
    "img_failed": {
        "en": "❌ Image generation failed.\nCheck: AI is on, EMERGENT_LLM_KEY is set, prompt is appropriate.",
        "fa": "❌ تولید تصویر ناموفق بود.\nبررسی کن: AI روشن باشه، EMERGENT_LLM_KEY ست شده باشه، prompt مناسب باشه.",
    },
    "img_send_failed": {"en": "❌ Failed to send image: {e}", "fa": "❌ ارسال تصویر ناموفق: {e}"},
    "imgmodel_show": {
        "en": "🎨 **Image model:** `{m}`\n\n🌟 Available models:\n  `{p}imgmodel gemini-3.1-flash-image-preview` ⚡ (default, Nano Banana)\n  `{p}imgmodel gemini-3-pro-image-preview` 🔥 (Pro, higher quality)",
        "fa": "🎨 **مدل تولید تصویر:** `{m}`\n\n🌟 مدل‌های موجود:\n  `{p}imgmodel gemini-3.1-flash-image-preview` ⚡ (پیش‌فرض، Nano Banana)\n  `{p}imgmodel gemini-3-pro-image-preview` 🔥 (Pro، کیفیت بالاتر)",
    },
    "imgmodel_set": {"en": "✅ Image model set to `{m}`.", "fa": "✅ مدل تولید تصویر به `{m}` تنظیم شد."},

    # Image edit
    "imgedit_usage": {
        "en": "🖼 **Image editing**\n\n🔧 How to use:\n1. Reply to a **message containing an image**\n2. Type: `{p}imgedit <change description>`\n\n📝 Examples:\n  `{p}imgedit make the background a starry night`\n  `{p}imgedit add a red hat on its head`\n  `{p}imgedit make it black and white vintage style`\n  `{p}imgedit add a rainbow in the sky`",
        "fa": "🖼 **ویرایش تصویر**\n\n🔧 طرز استفاده:\n۱. روی یه پیام **عکس‌دار** ریپلای بزن\n۲. تایپ کن: `{p}imgedit <توضیح تغییر>`\n\n📝 مثال:\n  `{p}imgedit پس‌زمینه رو شب پر ستاره بزن`\n  `{p}imgedit کلاه قرمز روی سرش بذار`\n  `{p}imgedit make it black and white vintage style`\n  `{p}imgedit add a rainbow in the sky`",
    },
    "imgedit_need_reply": {
        "en": "❌ You must reply to a **message containing an image**.",
        "fa": "❌ باید روی یه پیام **عکس‌دار** ریپلای بزنی.",
    },
    "imgedit_processing": {"en": "🖼 Editing image...\n_{p}_", "fa": "🖼 در حال ویرایش تصویر...\n_{p}_"},
    "imgedit_no_image": {"en": "❌ The replied message has no image.", "fa": "❌ پیام ریپلای شده عکس نداره."},
    "imgedit_dl_error": {"en": "❌ Error downloading image: {e}", "fa": "❌ خطا در دانلود تصویر: {e}"},
    "imgedit_invalid": {"en": "❌ Invalid image data received.", "fa": "❌ تصویر معتبر دریافت نشد."},
    "imgedit_failed": {
        "en": "❌ Image editing failed.\nThe model couldn't apply the prompt — try simpler text.",
        "fa": "❌ ویرایش تصویر ناموفق بود.\nاحتمالاً مدل نتونسته prompt رو پیاده کنه — متن ساده‌تر امتحان کن.",
    },
    "imgedit_caption": {"en": "🖼 **Edited:** {p}", "fa": "🖼 **ویرایش‌شده:** {p}"},

    # OCR (NEW)
    "ocr_usage": {
        "en": "📖 **OCR — Extract text from image**\n\n🔧 How to use:\n1. Reply to a **message containing an image**\n2. Type: `{p}ocr`\n\nThe extracted text will replace your command.",
        "fa": "📖 **OCR — استخراج متن از تصویر**\n\n🔧 طرز استفاده:\n۱. روی یه پیام **عکس‌دار** ریپلای بزن\n۲. تایپ کن: `{p}ocr`\n\nمتن استخراج‌شده جایگزین دستورت میشه.",
    },
    "ocr_need_reply": {
        "en": "❌ You must reply to a **message containing an image**.",
        "fa": "❌ باید روی یه پیام **عکس‌دار** ریپلای بزنی.",
    },
    "ocr_processing": {"en": "📖 Reading text from image...", "fa": "📖 در حال خواندن متن از تصویر..."},
    "ocr_no_image": {"en": "❌ The replied message has no image.", "fa": "❌ پیام ریپلای شده عکس نداره."},
    "ocr_dl_error": {"en": "❌ Error downloading image: {e}", "fa": "❌ خطا در دانلود تصویر: {e}"},
    "ocr_invalid": {"en": "❌ Invalid image data received.", "fa": "❌ تصویر معتبر دریافت نشد."},
    "ocr_no_text": {
        "en": "❌ No text found in the image (or unable to read it).",
        "fa": "❌ متنی در تصویر یافت نشد (یا قابل خوندن نبود).",
    },

    # Bot language
    "botlang_show": {
        "en": "🌍 **Bot UI Language:** `{l}`\n\n🛠 To change:\n  `{p}botlang en` — English (default)\n  `{p}botlang fa` — Persian\n\nℹ️ This only changes the bot's UI messages (help, status, errors). Auto-reply, AI responses, and translation work independently.",
        "fa": "🌍 **زبان رابط ربات:** `{l}`\n\n🛠 برای تغییر:\n  `{p}botlang en` — انگلیسی (پیش‌فرض)\n  `{p}botlang fa` — فارسی\n\nℹ️ این فقط زبان پیام‌های ربات (راهنما، وضعیت، خطاها) رو تغییر می‌ده. پاسخ‌های خودکار، AI و ترجمه مستقل کار می‌کنن.",
    },
    "botlang_invalid": {
        "en": "⚠️ Supported languages: `en`, `fa`",
        "fa": "⚠️ زبان‌های پشتیبانی شده: `en`, `fa`",
    },
    "botlang_set": {"en": "✅ Bot UI language changed to **{l}**.", "fa": "✅ زبان رابط ربات به **{l}** تغییر کرد."},

    # Search
    "search_usage": {
        "en": "🔍 **Global Search**\n\n  `{p}search <query>` — search **normal** chats (private + groups + channels)\n  `{p}searchall <query>` — search **only restricted/blocked** chats\n\n📝 Example:\n  `{p}search ali`\n  `{p}search 'meeting tomorrow'`\n\nResults are saved to a `.txt` file with chat names.",
        "fa": "🔍 **جستجوی جهانی در اکانت**\n\n  `{p}search <متن>` — جستجو در چت‌های **عادی** (خصوصی + گروه + کانال)\n  `{p}searchall <متن>` — جستجو **فقط** در کانال‌های **مسدود/محدود**\n\n📝 مثال:\n  `{p}search علی`\n  `{p}search 'جلسه فردا'`\n\nنتایج توی فایل `.txt` با مشخصات چت ذخیره میشن.",
    },
    "search_too_short": {
        "en": "⚠️ Search query must be at least 3 characters.",
        "fa": "⚠️ متن جستجو باید حداقل ۳ کاراکتر باشه.",
    },
    "search_starting": {
        "en": "🔍 Searching `{q}` across all your chats...\n_This may take a while depending on number of chats. Progress updates every 500 chats._",
        "fa": "🔍 در حال جستجوی `{q}` در همه چت‌هات...\n_بسته به تعداد چت‌ها ممکنه طول بکشه. آپدیت پیشرفت هر ۵۰۰ چت._",
    },
    "search_starting_restricted": {
        "en": "🔒 Searching `{q}` in restricted/blocked channels only...\n_Progress updates every 500 chats._",
        "fa": "🔒 در حال جستجوی `{q}` فقط در کانال‌های مسدود/محدود...\n_آپدیت پیشرفت هر ۵۰۰ چت._",
    },
    "search_progress": {
        "en": "🔍 Searching... `{done}/{total}` chats checked, **{m}** matches so far.",
        "fa": "🔍 در حال جستجو... `{done}/{total}` چت بررسی شد، **{m}** نتیجه تاکنون.",
    },
    "search_no_results": {
        "en": "❌ No results found for `{q}` in {n} chats.",
        "fa": "❌ هیچ نتیجه‌ای برای `{q}` در {n} چت یافت نشد.",
    },
    "search_no_restricted": {
        "en": "❌ No restricted/blocked channels found in your account.",
        "fa": "❌ هیچ کانال مسدود یا محدودی توی اکانتت پیدا نشد.",
    },
    "search_caption": {
        "en": "🔍 Search: \"{q}\"\n📊 {n} matches across {c} chats\n📁 See attached file for details.",
        "fa": "🔍 جستجو: \"{q}\"\n📊 {n} نتیجه در {c} چت\n📁 جزئیات در فایل پیوست.",
    },
    "search_caption_restricted": {
        "en": "🔒 Restricted Search: \"{q}\"\n📊 {n} matches across {c} restricted/blocked chats\n📁 See attached file for details.",
        "fa": "🔒 جستجو در محدودها: \"{q}\"\n📊 {n} نتیجه در {c} چت مسدود/محدود\n📁 جزئیات در فایل پیوست.",
    },

    # Stats
    "stats_title": {"en": "📊 **Bidar Stats & Settings**", "fa": "📊 **آمار و تنظیمات Bidar**"},
    "stats_uptime": {"en": "⏱ Uptime", "fa": "⏱ آپ‌تایم"},
    "stats_online": {"en": "📡 Always Online", "fa": "📡 آنلاین دائم"},
    "stats_refresh": {"en": "🔄 Refresh interval", "fa": "🔄 بازه رفرش"},
    "stats_autoreply": {"en": "🤖 Auto-reply", "fa": "🤖 پاسخ خودکار"},
    "stats_ai": {"en": "🧠 **AI Assistant:**", "fa": "🧠 **دستیار AI:**"},
    "stats_ai_model": {"en": "📚 Model", "fa": "📚 مدل"},
    "stats_ai_groups": {"en": "💬 In groups", "fa": "💬 در گروه‌ها"},
    "stats_ai_groupcd": {"en": "⏳ Group cooldown", "fa": "⏳ Group cooldown"},
    "stats_ai_sessions": {"en": "🗂 Active conversations", "fa": "🗂 مکالمات فعال"},
    "stats_received": {"en": "📨 Messages received", "fa": "📨 پیام‌های دریافتی"},
    "stats_sent": {"en": "✉️ Replies sent", "fa": "✉️ پاسخ‌های ارسالی"},
    "stats_ai_replies": {"en": "🤖 AI replies", "fa": "🤖 پاسخ‌های AI"},
    "stats_cooldown": {"en": "⏳ Cooldown", "fa": "⏳ Cooldown"},
    "stats_fallback": {"en": "📝 Fallback message:", "fa": "📝 متن ثابت (fallback):"},
    "stats_ai_warn": {
        "en": "⚠️ AI is enabled but unusable: {err}",
        "fa": "⚠️ AI فعاله ولی غیرقابل استفاده: {err}",
    },

    # Alive
    "alive_text": {
        "en": "✨ **Bidar is alive and online** 🌙\n\n⏱ Uptime: `{u}`\n📡 Online: `{on}`\n🤖 Auto-reply: `{rp}`\n🧠 AI: `{ai}`\n🌍 UI: `{lang}`\n🔖 Version: `v{v}`",
        "fa": "✨ **Bidar زنده و آنلاینه** 🌙\n\n⏱ آپ‌تایم: `{u}`\n📡 آنلاین: `{on}`\n🤖 پاسخ خودکار: `{rp}`\n🧠 AI: `{ai}`\n🌍 UI: `{lang}`\n🔖 نسخه: `v{v}`",
    },

    # ID
    "id_chat": {"en": "🆔 Chat ID: `{id}`", "fa": "🆔 Chat ID: `{id}`"},
    "id_user": {"en": "👤 User ID (reply): `{id}`", "fa": "👤 User ID (reply): `{id}`"},

    # Restart
    "restart_msg": {
        "en": "♻️ Restarting... (systemd will bring it back up)",
        "fa": "♻️ در حال ری‌استارت... (systemd دوباره بالا میاره)",
    },

    # Help — full text (long)
    "help_full": {
        "en": (
            "🤖 **Bidar — Full Command Guide**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📡 **Online Status**\n"
            "  `{p}online on|off` — always online\n"
            "  `{p}interval <s>` — refresh interval (default 240s)\n\n"
            "🤖 **Static Auto-reply**\n"
            "  `{p}reply on|off` — toggle\n"
            "  `{p}setmsg <text>` — edit reply message\n"
            "  `{p}afk [text]` — quick AFK shortcut\n\n"
            "🧠 **AI Assistant**\n"
            "  `{p}ai on|off` — toggle AI\n"
            "  `{p}aigroups on|off` — AI in groups\n"
            "  `{p}personality <text>` — set AI personality\n"
            "  `{p}personality reset` — reset to default\n"
            "  `{p}aimodel <model>` — change AI model\n"
            "  `{p}groupcd <s>` — group cooldown (0=no limit)\n"
            "  `{p}aireset` — clear AI conversation memory\n"
            "  `{p}r [hint]` — **manually generate** AI reply for current chat\n\n"
            "🌐 **Translation**\n"
            "  `{p}lang <code>` — set default target language\n"
            "  `{p}tl <text>` — translate to default language\n"
            "  reply + `{p}tl` — translate replied message\n"
            "  `{p}to <code> <text>` — edit message to that language\n"
            "     example: `{p}to en سلام چطوری`\n\n"
            "🎨 **Image**\n"
            "  `{p}img <description>` — generate image (Nano Banana)\n"
            "  `{p}imgedit <change>` — edit image (reply to image)\n"
            "  `{p}ocr` — extract text from image (reply to image)\n"
            "  `{p}imgmodel <model>` — change image model\n\n"
            "🔎 **Search**\n"
            "  `{p}search <query>` — search normal chats → saves .txt file\n"
            "  `{p}searchall <query>` — search **only** restricted/blocked channels\n\n"
            "📊 **Info**\n"
            "  `{p}alive` — health check\n"
            "  `{p}ping` — latency test\n"
            "  `{p}stats` — full stats & settings\n"
            "  `{p}id` — chat / user ID\n\n"
            "🔧 **Admin**\n"
            "  `{p}botlang <en|fa>` — change UI language\n"
            "  `{p}restart` — restart (systemd mode)\n"
            "  `{p}help` | `{p}menu` | `{p}commands` — this help\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 All commands are owner-only.  🔖 v{v}"
        ),
        "fa": (
            "🤖 **Bidar — راهنمای کامل دستورات**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📡 **وضعیت آنلاین**\n"
            "  `{p}online on|off` — آنلاین دائم\n"
            "  `{p}interval <s>` — بازه رفرش (پیش‌فرض ۲۴۰s)\n\n"
            "🤖 **پاسخ خودکار ثابت**\n"
            "  `{p}reply on|off` — روشن/خاموش\n"
            "  `{p}setmsg <متن>` — ویرایش متن\n"
            "  `{p}afk [متن]` — میانبر AFK\n\n"
            "🧠 **دستیار AI**\n"
            "  `{p}ai on|off` — روشن/خاموش AI\n"
            "  `{p}aigroups on|off` — AI در گروه‌ها\n"
            "  `{p}personality <متن>` — تنظیم شخصیت\n"
            "  `{p}personality reset` — ریست به پیش‌فرض\n"
            "  `{p}aimodel <مدل>` — تغییر مدل\n"
            "  `{p}groupcd <s>` — cooldown گروه (۰=بدون محدودیت)\n"
            "  `{p}aireset` — پاک کردن حافظه مکالمات\n"
            "  `{p}r [hint]` — **تولید پاسخ دستی** با AI بر اساس چت فعلی\n\n"
            "🌐 **ترجمه**\n"
            "  `{p}lang <code>` — تنظیم زبان پیش‌فرض (fa, en, ar, ...)\n"
            "  `{p}tl <متن>` — ترجمه به زبان پیش‌فرض\n"
            "  ریپلای + `{p}tl` — ترجمه پیام ریپلای شده\n"
            "  `{p}to <code> <متن>` — متن رو ادیت می‌کنه به زبان دیگه\n"
            "     مثال: `{p}to en سلام چطوری`\n\n"
            "🎨 **تصویر**\n"
            "  `{p}img <توضیح>` — تولید تصویر با Nano Banana\n"
            "  `{p}imgedit <توضیح>` — ویرایش عکس (روی عکس reply بزن)\n"
            "  `{p}ocr` — استخراج متن از عکس (روی عکس reply بزن)\n"
            "  `{p}imgmodel <model>` — تغییر مدل تصویر\n\n"
            "🔎 **جستجو**\n"
            "  `{p}search <متن>` — جستجو در چت‌های عادی → فایل .txt میده\n"
            "  `{p}searchall <متن>` — جستجو **فقط** در کانال‌های محدود/مسدود\n\n"
            "📊 **اطلاعات**\n"
            "  `{p}alive` — چک زنده بودن ربات\n"
            "  `{p}ping` — تست تاخیر (ms)\n"
            "  `{p}stats` — همه آمار و تنظیمات فعلی\n"
            "  `{p}id` — آیدی چت/کاربر\n\n"
            "🔧 **مدیریت**\n"
            "  `{p}botlang <en|fa>` — تغییر زبان رابط\n"
            "  `{p}restart` — ری‌استارت (در حالت systemd)\n"
            "  `{p}help` | `{p}menu` | `{p}commands` — همین راهنما\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 همه دستورات فقط برای خودت کار میکنن.  🔖 v{v}"
        ),
    },
}


def t(key: str, **kwargs) -> str:
    """Get a localized message. Falls back to English, then to the key itself."""
    lang = config.get("bot_lang", "en")
    entry = I18N.get(key, {})
    text = entry.get(lang) or entry.get("en") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


# ───────────────────────── Helpers ─────────────────────────
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
            log.warning(f"⛔ Unauthorized access attempt by {event.sender_id} to {handler.__name__}")
            return
        await handler(event)
    wrapper.__name__ = handler.__name__
    return wrapper


def _parse_on_off(arg: str | None, current: bool) -> bool:
    if arg is None:
        return not current
    return arg.strip().lower() in {"on", "روشن", "1", "true", "yes"}


def _state_label(value: bool) -> str:
    return t("on") if value else t("off")


def _infer_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return "gemini"


def _ai_ready() -> tuple[bool, str]:
    if not AI_LIB_OK:
        return False, "emergentintegrations library not installed"
    if not EMERGENT_LLM_KEY:
        return False, "EMERGENT_LLM_KEY not set in .env"
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


# ────── Translate / Image generate / Image edit / OCR helpers ──────
async def _translate_text(text: str, target_lang: str) -> str | None:
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
        msg = UserMessage(text=edit_prompt, file_contents=[ImageContent(image_b64)])
        _text, images = await chat.send_message_multimodal_response(msg)
        if not images:
            log.warning("Image edit: no images returned")
            return None
        return base64.b64decode(images[0]["data"])
    except Exception as e:  # noqa: BLE001
        log.error(f"Image edit error: {e}")
        return None


async def _ocr_image(image_bytes: bytes) -> str | None:
    """Extract all text from an image. Returns extracted text, or None if no text/error."""
    ready, _ = _ai_ready()
    if not ready or not image_bytes:
        return None
    try:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"ocr-{time.time_ns()}",
            system_message=(
                "You are an OCR (Optical Character Recognition) assistant. "
                "Your task is to extract ALL text visible in the image exactly as it appears. "
                "Rules:\n"
                "1. Output ONLY the extracted text — no commentary, no explanations, no labels.\n"
                "2. Preserve original formatting: line breaks, paragraphs, lists, indentation.\n"
                "3. Maintain the original language of the text (do NOT translate).\n"
                "4. Include all visible text: titles, body, captions, watermarks, numbers, symbols.\n"
                "5. If text is in multiple columns, read top-to-bottom, left-to-right.\n"
                "6. If the image contains NO readable text at all, output exactly: NO_TEXT_FOUND"
            ),
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        msg = UserMessage(
            text="Extract all text visible in this image, preserving its exact formatting.",
            file_contents=[ImageContent(image_b64)],
        )
        resp = await chat.send_message(msg)
        text = str(resp).strip()
        if not text or text == "NO_TEXT_FOUND" or text.lower().startswith("no_text_found"):
            return None
        return text
    except Exception as e:  # noqa: BLE001
        log.error(f"OCR error: {e}")
        return None


# ────────── Search Helpers ──────────
def _classify_dialog(dialog) -> str:
    """Returns 'private', 'bot', 'group', or 'channel'."""
    if dialog.is_user:
        entity = dialog.entity
        if getattr(entity, "bot", False):
            return "bot"
        return "private"
    if dialog.is_group:
        return "group"
    return "channel"


async def _search_all_chats(
    query: str,
    *,
    only_restricted: bool = False,
    skip_bots: bool = True,
    limit_per_chat: int = 100,
    on_progress=None,
) -> tuple[list[dict], int, int, int, list[str]]:
    """
    Search across all dialogs.
    Args:
        only_restricted: If True, search ONLY in restricted/blocked dialogs.
                         If False, search only in NORMAL dialogs, skipping restricted ones.
    Returns (results, total_dialogs, searched, skipped, errors).
    """
    # Step 1: collect dialogs
    dialogs = []
    async for d in client.iter_dialogs():
        dialogs.append(d)
    total_dialogs = len(dialogs)

    results: list[dict] = []
    searched = 0
    skipped = 0
    errors: list[str] = []

    for idx, dialog in enumerate(dialogs):
        chat_type = _classify_dialog(dialog)

        # Optional filters
        if skip_bots and chat_type == "bot":
            skipped += 1
            continue

        is_restricted = bool(getattr(dialog.entity, "restricted", False))

        if only_restricted:
            # Only process restricted/blocked dialogs; skip everything else
            if not is_restricted:
                skipped += 1
                continue
        else:
            # Normal mode: skip restricted dialogs entirely
            if is_restricted:
                skipped += 1
                continue

        try:
            chat_matches = []
            async for msg in client.iter_messages(dialog.entity, search=query, limit=limit_per_chat):
                msg_text = msg.text or msg.message or ""
                if not msg_text:
                    continue
                chat_matches.append({
                    "id": msg.id,
                    "text": msg_text,
                    "date": msg.date,
                    "sender_id": msg.sender_id,
                })

            if chat_matches:
                results.append({
                    "name": dialog.name or "Unknown",
                    "id": dialog.id,
                    "type": chat_type,
                    "restricted": is_restricted,
                    "matches": chat_matches,
                })
            searched += 1

        except FloodWaitError as e:
            errors.append(f"{dialog.name}: rate-limited, waited {e.seconds}s")
            await asyncio.sleep(min(e.seconds + 1, 60))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{dialog.name}: {type(e).__name__}: {e}")

        # Progress callback every 500 chats (avoid Telegram edit rate-limit)
        if on_progress and (idx + 1) % 500 == 0:
            total_matches_so_far = sum(len(r["matches"]) for r in results)
            try:
                await on_progress(idx + 1, total_dialogs, total_matches_so_far)
            except Exception:  # noqa: BLE001
                pass

    return results, total_dialogs, searched, skipped, errors


def _format_search_report(
    query: str,
    results: list[dict],
    total_dialogs: int,
    searched: int,
    skipped: int,
    errors: list[str],
    only_restricted: bool = False,
) -> str:
    """Format search results into a human-readable text report."""
    from datetime import datetime as _dt

    total_matches = sum(len(r["matches"]) for r in results)
    chats_with_matches = len(results)

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("🔍 BIDAR SEARCH REPORT")
    lines.append("=" * 70)
    lines.append(f"Query:           \"{query}\"")
    lines.append(f"Generated at:    {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mode_label = "Restricted/Blocked channels ONLY" if only_restricted else "Normal chats only"
    lines.append(f"Mode:            {mode_label}")
    lines.append(f"Total dialogs:   {total_dialogs}")
    lines.append(f"Searched:        {searched}")
    if skipped:
        reason = "non-restricted + bots" if only_restricted else "bots + restricted"
        lines.append(f"Skipped:         {skipped} ({reason})")
    lines.append(f"Total matches:   {total_matches}")
    lines.append(f"Chats matched:   {chats_with_matches}")
    lines.append("=" * 70)
    lines.append("")

    if not results:
        lines.append("No matching messages found.")
        return "\n".join(lines)

    # Sort: chats with most matches first
    results = sorted(results, key=lambda r: len(r["matches"]), reverse=True)

    for idx, chat in enumerate(results, start=1):
        lines.append("")
        lines.append("─" * 70)
        flag = " 🔒RESTRICTED" if chat.get("restricted") else ""
        lines.append(f"#{idx}. 📁 {chat['name']}{flag}")
        lines.append(f"     ID:      {chat['id']}")
        lines.append(f"     Type:    {chat['type']}")
        lines.append(f"     Matches: {len(chat['matches'])}")
        lines.append("─" * 70)

        for m in chat["matches"]:
            date_str = m["date"].strftime("%Y-%m-%d %H:%M:%S") if m["date"] else "(unknown)"
            text = m["text"]
            if len(text) > 800:
                text = text[:800] + " ... [truncated]"
            sender = f" (sender_id={m['sender_id']})" if m.get("sender_id") else ""
            lines.append("")
            lines.append(f"  📅 [{date_str}] msg_id={m['id']}{sender}")
            for tline in text.split("\n"):
                lines.append(f"     > {tline}")

    if errors:
        lines.append("")
        lines.append("=" * 70)
        lines.append("⚠️ Errors encountered:")
        lines.append("=" * 70)
        for e in errors[:50]:
            lines.append(f"  • {e}")
        if len(errors) > 50:
            lines.append(f"  ... and {len(errors) - 50} more errors")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"End of report — generated by Bidar v{VERSION}")
    lines.append("=" * 70)

    return "\n".join(lines)


async def _do_search_and_send(event, query: str, only_restricted: bool) -> None:
    """
    Shared logic for both .search and .searchall commands.

    Args:
        only_restricted: If True, search ONLY in restricted/blocked channels (.searchall).
                         If False, search only in NORMAL chats, skipping restricted ones (.search).
    """
    if len(query) < 3:
        await event.edit(t("search_too_short"))
        return

    start_key = "search_starting_restricted" if only_restricted else "search_starting"
    msg = await event.edit(t(start_key, q=query[:80]))

    async def _on_progress(done: int, total: int, matches: int) -> None:
        try:
            await msg.edit(t("search_progress", done=done, total=total, m=matches))
        except Exception:  # noqa: BLE001
            pass

    results, total, searched, skipped, errors = await _search_all_chats(
        query,
        only_restricted=only_restricted,
        on_progress=_on_progress,
    )

    total_matches = sum(len(r["matches"]) for r in results)

    if not results:
        # Special case: zero restricted channels in account
        if only_restricted and searched == 0:
            await msg.edit(t("search_no_restricted"))
            return
        await msg.edit(t("search_no_results", q=query[:80], n=searched))
        return

    report = _format_search_report(
        query, results, total, searched, skipped, errors,
        only_restricted=only_restricted,
    )

    # Save to a temp file with a friendly name
    safe_query = "".join(c if c.isalnum() else "_" for c in query[:30]).strip("_") or "query"
    prefix = "bidar_search_restricted_" if only_restricted else "bidar_search_"
    fname = f"{prefix}{safe_query}_{int(time.time())}.txt"
    tmp_path = Path(tempfile.gettempdir()) / fname
    try:
        tmp_path.write_text(report, encoding="utf-8")
        caption_key = "search_caption_restricted" if only_restricted else "search_caption"
        caption = t(caption_key, q=query[:200], n=total_matches, c=len(results))
        await client.send_file(
            event.chat_id,
            str(tmp_path),
            caption=caption,
            force_document=True,
            reply_to=event.reply_to_msg_id,
        )
        await msg.delete()
        log.info(
            f"[.search{'all' if only_restricted else ''}] query={query!r} "
            f"matches={total_matches} chats={len(results)}"
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Search send file error: {e}")
        await msg.edit(f"❌ Error sending results file: {e}")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


# ─────────────────── Background: online keeper ───────────────────
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
                    log.info("📴 Status: offline")
                else:
                    log.debug("🟢 Online status refreshed")
        except Exception as e:  # noqa: BLE001
            log.error(f"online_keeper: {e}")
        interval = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
        interval = max(MIN_ONLINE_INTERVAL, min(MAX_ONLINE_INTERVAL, interval))
        await asyncio.sleep(interval)


# ═══════════════════════════════════════════════════════════════════
# ║                       Userbot Commands                            ║
# ═══════════════════════════════════════════════════════════════════
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
    await event.edit(t("online_set", state=_state_label(new)))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}interval(?:\s+(\d+)([smSM]?))?$"))
@owner_only
async def cmd_interval(event):
    num = event.pattern_match.group(1)
    unit = (event.pattern_match.group(2) or "s").lower()
    if num is None:
        cur = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
        await event.edit(t("interval_show",
                           cur=cur, m=cur // 60, s=cur % 60,
                           mn=MIN_ONLINE_INTERVAL, mx=MAX_ONLINE_INTERVAL, p=CMD_PREFIX))
        return
    value = int(num)
    if unit == "m":
        value *= 60
    if value < MIN_ONLINE_INTERVAL or value > MAX_ONLINE_INTERVAL:
        await event.edit(t("interval_out_of_range", mn=MIN_ONLINE_INTERVAL, mx=MAX_ONLINE_INTERVAL))
        return
    config["online_refresh_interval"] = value
    save_config()
    await event.edit(t("interval_updated", v=value, m=value // 60, s=value % 60))


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
    await event.edit(t("reply_set", state=_state_label(new), msg=config["autoreply_message"]))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}setmsg\s+([\s\S]+)$"))
@owner_only
async def cmd_setmsg(event):
    new_msg = event.pattern_match.group(1).strip()
    config["autoreply_message"] = new_msg
    save_config()
    await event.edit(t("setmsg_done", msg=new_msg))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}afk(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_afk(event):
    reason = event.pattern_match.group(1)
    reason_l = reason.strip().lower() if reason else None
    if reason_l in {"off", "خاموش"}:
        config["autoreply_enabled"] = False
        replied_users.clear()
        save_config()
        await event.edit(t("afk_off"))
        return
    if reason and reason_l not in {"on", "روشن"}:
        config["autoreply_message"] = reason.strip()
    config["autoreply_enabled"] = True
    save_config()
    await event.edit(t("afk_on", msg=config["autoreply_message"]))


# ═════════ AI ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ai(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_ai(event):
    arg = event.pattern_match.group(1)
    ready, err_msg = _ai_ready()
    if not ready:
        await event.edit(t("ai_not_ready", err=err_msg))
        return
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config.get("ai_enabled", False),
    )
    config["ai_enabled"] = new
    save_config()
    await event.edit(t("ai_set",
                       state=_state_label(new),
                       model=config["ai_model"],
                       groups=t("on") if config.get("ai_groups_enabled") else t("off")))


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
    await event.edit(t("aigroups_set", state=_state_label(new)))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}personality(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_personality(event):
    new_text = event.pattern_match.group(1)
    if new_text is None:
        await event.edit(t("personality_show", p=config["ai_personality"], prefix=CMD_PREFIX))
        return
    text = new_text.strip()
    if text.lower() in {"reset", "default", "پیشفرض"}:
        config["ai_personality"] = DEFAULT_AI_PERSONALITY
    else:
        config["ai_personality"] = text
    save_config()
    _reset_chat_sessions()
    await event.edit(t("personality_updated", p=config["ai_personality"]))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aimodel(?:\s+(\S+))?$"))
@owner_only
async def cmd_aimodel(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(t("aimodel_show", m=config["ai_model"], p=CMD_PREFIX))
        return
    config["ai_model"] = arg
    save_config()
    _reset_chat_sessions()
    await event.edit(t("aimodel_updated", m=arg, prov=_infer_provider(arg)))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aireset$"))
@owner_only
async def cmd_aireset(event):
    count = len(_chat_sessions)
    _reset_chat_sessions()
    await event.edit(t("aireset_done", n=count))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}groupcd(?:\s+(\d+))?$"))
@owner_only
async def cmd_groupcd(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        cur = int(config.get("group_cooldown", DEFAULT_GROUP_COOLDOWN))
        note = t("no_limit") if cur == 0 else f"(~{cur // 60}m {cur % 60}s)"
        await event.edit(t("groupcd_show", cur=cur, note=note, p=CMD_PREFIX))
        return
    value = int(arg)
    if value < 0 or value > 3600:
        await event.edit(t("groupcd_invalid"))
        return
    config["group_cooldown"] = value
    save_config()
    state = t("no_limit") + " ⚡" if value == 0 else f"`{value}s`"
    await event.edit(t("groupcd_updated", v=state))


# ═════════ .r — manual AI reply generation ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}r(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_generate_reply(event):
    ready, err = _ai_ready()
    if not ready:
        await event.edit(t("ai_not_ready", err=err))
        return

    hint = event.pattern_match.group(1)
    await event.edit(t("r_thinking"))

    context_lines: list[str] = []
    try:
        async for msg in client.iter_messages(event.chat_id, limit=20):
            if msg.id == event.id:
                continue
            text = (msg.raw_text or msg.text or "").strip()
            if not text or text.startswith(CMD_PREFIX):
                continue
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
        context_lines.reverse()
    except Exception as e:  # noqa: BLE001
        log.warning(f"cmd_r: failed to fetch context: {e}")

    target_text: str | None = None
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
            if replied:
                tt = (replied.raw_text or replied.text or "").strip()
                if tt:
                    target_text = tt[:500]
        except Exception:  # noqa: BLE001
            pass

    context_str = "\n".join(context_lines) if context_lines else "(no recent context)"
    chat_type = "private chat" if event.is_private else "group chat"

    system_msg = (
        f"You are replying as 'You' in a real Telegram conversation. This is a {chat_type}. "
        "Generate a natural, contextually-appropriate message that 'You' would send right now. "
        "Match the tone, style, and language of the conversation (if it's Persian, reply in Persian; "
        "if English, reply in English; etc). Keep it short and natural. "
        "Do NOT introduce yourself as AI, bot, or assistant. "
        "Output ONLY the message text — no quotes, no labels, no explanations."
    )
    parts = [f"Recent conversation:\n{context_str}"]
    if target_text:
        parts.append(f"\n(Focus on this message:)\n{target_text}")
    if hint:
        parts.append(f"\n(Additional instruction: {hint})")
    parts.append("\nNow write the reply:")
    user_prompt = "\n".join(parts)

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"genreply-{time.time_ns()}",
            system_message=system_msg,
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        resp = await chat.send_message(UserMessage(text=user_prompt))
        reply_text = str(resp).strip()
        if (reply_text.startswith('"') and reply_text.endswith('"')) or \
           (reply_text.startswith("«") and reply_text.endswith("»")):
            reply_text = reply_text[1:-1].strip()
        if not reply_text:
            await event.edit(t("r_no_response"))
            return
        stats["ai_replies"] += 1
        await event.edit(reply_text)
        log.info(f"[.r] generated in chat={event.chat_id} len={len(reply_text)}")
    except Exception as e:  # noqa: BLE001
        log.error(f"cmd_r error: {e}")
        await event.edit(t("r_error", e=str(e)))


# ═════════ Translation ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}lang(?:\s+([a-zA-Z\-]+))?$"))
@owner_only
async def cmd_lang(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(t("lang_show", l=config.get("translate_target", "fa"), p=CMD_PREFIX))
        return
    config["translate_target"] = arg.lower()
    save_config()
    await event.edit(t("lang_set", l=arg.lower()))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}tl(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_translate(event):
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
                await event.edit(t("tl_no_text"))
                return
        except Exception as e:  # noqa: BLE001
            await event.edit(t("tl_reply_error", e=str(e)))
            return
    else:
        await event.edit(t("tl_usage", p=CMD_PREFIX, t=target))
        return
    msg = await event.edit(t("tl_processing"))
    translated = await _translate_text(source_text, target)
    if translated:
        await msg.edit(t("tl_result", t=target, txt=translated))
    else:
        await msg.edit(t("tl_failed"))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}to\s+([a-zA-Z\-]+)\s+([\s\S]+)$"))
@owner_only
async def cmd_to(event):
    target = event.pattern_match.group(1).lower()
    text = event.pattern_match.group(2).strip()
    msg = await event.edit(t("to_processing"))
    translated = await _translate_text(text, target)
    if translated:
        await msg.edit(translated)
    else:
        await msg.edit(t("to_failed", txt=text))


# ═════════ Image generation / edit / OCR ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}img(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_image(event):
    prompt = event.pattern_match.group(1)
    if not prompt or not prompt.strip():
        await event.edit(t("img_usage",
                           p=CMD_PREFIX,
                           m=config.get("image_model", "gemini-3.1-flash-image-preview")))
        return
    prompt = prompt.strip()
    msg = await event.edit(t("img_processing", p=prompt[:100]))
    img_bytes = await _generate_image(prompt)
    if not img_bytes:
        await msg.edit(t("img_failed"))
        return
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_bytes)
            tmp = f.name
        await client.send_file(
            event.chat_id, tmp,
            caption=f"🎨 {prompt[:1000]}",
            reply_to=event.reply_to_msg_id,
        )
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.error(f"Send image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}imgmodel(?:\s+(\S+))?$"))
@owner_only
async def cmd_imgmodel(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(t("imgmodel_show",
                           m=config.get("image_model", "gemini-3.1-flash-image-preview"),
                           p=CMD_PREFIX))
        return
    config["image_model"] = arg
    save_config()
    await event.edit(t("imgmodel_set", m=arg))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}imgedit(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_imgedit(event):
    prompt = event.pattern_match.group(1)
    if not prompt or not prompt.strip():
        await event.edit(t("imgedit_usage", p=CMD_PREFIX))
        return
    if not event.is_reply:
        await event.edit(t("imgedit_need_reply"))
        return
    prompt = prompt.strip()
    msg = await event.edit(t("imgedit_processing", p=prompt[:100]))
    try:
        replied = await event.get_reply_message()
    except Exception as e:  # noqa: BLE001
        await msg.edit(t("imgedit_dl_error", e=str(e)))
        return
    if not replied or not replied.media:
        await msg.edit(t("imgedit_no_image"))
        return
    try:
        img_bytes = await client.download_media(replied, file=bytes)
    except Exception as e:  # noqa: BLE001
        await msg.edit(t("imgedit_dl_error", e=str(e)))
        return
    if not img_bytes or not isinstance(img_bytes, bytes):
        await msg.edit(t("imgedit_invalid"))
        return
    edited_bytes = await _edit_image(img_bytes, prompt)
    if not edited_bytes:
        await msg.edit(t("imgedit_failed"))
        return
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(edited_bytes)
            tmp = f.name
        await client.send_file(
            event.chat_id, tmp,
            caption=t("imgedit_caption", p=prompt[:900]),
            reply_to=replied.id,
        )
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.error(f"Send edited image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ═════════ OCR (NEW) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}ocr$"))
@owner_only
async def cmd_ocr(event):
    """Extract text from an image. Reply to a message containing an image."""
    if not event.is_reply:
        await event.edit(t("ocr_need_reply"))
        return
    msg = await event.edit(t("ocr_processing"))
    try:
        replied = await event.get_reply_message()
    except Exception as e:  # noqa: BLE001
        await msg.edit(t("ocr_dl_error", e=str(e)))
        return
    if not replied or not replied.media:
        await msg.edit(t("ocr_no_image"))
        return
    try:
        img_bytes = await client.download_media(replied, file=bytes)
    except Exception as e:  # noqa: BLE001
        await msg.edit(t("ocr_dl_error", e=str(e)))
        return
    if not img_bytes or not isinstance(img_bytes, bytes):
        await msg.edit(t("ocr_invalid"))
        return
    extracted = await _ocr_image(img_bytes)
    if not extracted:
        await msg.edit(t("ocr_no_text"))
        return
    # Replace the command message with extracted text.
    # If extremely long, send as a separate reply to keep it readable.
    if len(extracted) > 3500:
        await msg.edit(extracted[:3500] + "\n\n...")
        # Send remainder as reply
        chunks = [extracted[i:i + 3800] for i in range(3500, len(extracted), 3800)]
        for chunk in chunks:
            await client.send_message(event.chat_id, chunk, reply_to=replied.id)
    else:
        await msg.edit(extracted)
    log.info(f"[.ocr] extracted {len(extracted)} chars from image")


# ═════════ Bot UI Language ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}botlang(?:\s+(\S+))?$"))
@owner_only
async def cmd_botlang(event):
    """Switch the bot UI language between English and Persian."""
    arg = event.pattern_match.group(1)
    if arg is None:
        await event.edit(t("botlang_show", l=config.get("bot_lang", "en"), p=CMD_PREFIX))
        return
    new_lang = arg.lower()
    if new_lang not in {"en", "fa"}:
        await event.edit(t("botlang_invalid"))
        return
    config["bot_lang"] = new_lang
    save_config()
    await event.edit(t("botlang_set", l=new_lang))


# ═════════ Search (Global) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}search(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_search(event):
    """Search across NORMAL chats only (private + groups + non-restricted channels)."""
    arg = event.pattern_match.group(1)
    if not arg or not arg.strip():
        await event.edit(t("search_usage", p=CMD_PREFIX))
        return
    query = arg.strip()
    await _do_search_and_send(event, query, only_restricted=False)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}searchall(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_searchall(event):
    """Search ONLY in restricted/blocked channels."""
    arg = event.pattern_match.group(1)
    if not arg or not arg.strip():
        await event.edit(t("search_usage", p=CMD_PREFIX))
        return
    query = arg.strip()
    await _do_search_and_send(event, query, only_restricted=True)


# ═════════ Info commands ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
@owner_only
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    interval = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
    ready, ai_err = _ai_ready()
    ai_state = t("on") if (config.get("ai_enabled") and ready) else t("off")
    text = (
        f"{t('stats_title')}\n\n"
        f"{t('stats_uptime')}: `{_fmt_uptime(uptime)}`\n"
        f"{t('stats_online')}: `{_state_label(config['online_enabled'])}`\n"
        f"{t('stats_refresh')}: `{interval}s` (~{interval // 60}m)\n"
        f"{t('stats_autoreply')}: `{_state_label(config['autoreply_enabled'])}`\n\n"
        f"{t('stats_ai')} `{ai_state}`\n"
        f"  {t('stats_ai_model')}: `{config['ai_model']}`\n"
        f"  {t('stats_ai_groups')}: `{t('on') if config.get('ai_groups_enabled') else t('off')}`\n"
        f"  {t('stats_ai_groupcd')}: `{config.get('group_cooldown', 0)}s`"
        f"{(' ' + t('no_limit')) if config.get('group_cooldown', 0) == 0 else ''}\n"
        f"  {t('stats_ai_sessions')}: `{len(_chat_sessions)}`\n\n"
        f"{t('stats_received')}: `{stats['messages_received']}`\n"
        f"{t('stats_sent')}: `{stats['replies_sent']}`\n"
        f"{t('stats_ai_replies')}: `{stats['ai_replies']}`\n"
        f"{t('stats_cooldown')}: `{config['autoreply_cooldown']}s`\n\n"
        f"{t('stats_fallback')}\n`{config['autoreply_message']}`"
    )
    if not ready and config.get("ai_enabled"):
        text += "\n\n" + t("stats_ai_warn", err=ai_err)
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}alive$"))
@owner_only
async def cmd_alive(event):
    uptime = time.time() - stats["start_time"]
    await event.edit(t("alive_text",
                       u=_fmt_uptime(uptime),
                       on=_state_label(config['online_enabled']),
                       rp=_state_label(config['autoreply_enabled']),
                       ai=_state_label(config.get('ai_enabled', False)),
                       lang=config.get('bot_lang', 'en'),
                       v=VERSION))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}id$"))
@owner_only
async def cmd_id(event):
    chat = await event.get_chat()
    out = t("id_chat", id=chat.id)
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id:
            out += "\n" + t("id_user", id=replied.sender_id)
    await event.edit(out)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}restart$"))
@owner_only
async def cmd_restart(event):
    await event.edit(t("restart_msg"))
    log.info("Restart command → disconnecting.")
    await client.disconnect()


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(help|menu|commands)$"))
@owner_only
async def cmd_help(event):
    await event.edit(t("help_full", p=CMD_PREFIX, v=VERSION))


# ═══════════════════════════════════════════════════════════════════
# ║                  Incoming message handler                          ║
# ═══════════════════════════════════════════════════════════════════
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
    if config.get("ai_enabled"):
        ready, _ = _ai_ready()
        if ready:
            session_id = f"private_{sender.id}"
            response_text = await _ai_respond(session_id, event.raw_text or "")
    if not response_text:
        response_text = config["autoreply_message"]
    try:
        await event.reply(response_text)
        replied_users[sender.id] = now
        stats["replies_sent"] += 1
        log.info(
            f"Replied to {getattr(sender, 'first_name', '?')} (id={sender.id}) — "
            f"{'AI' if config.get('ai_enabled') else 'static'}"
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Reply failed: {e}")


async def _handle_group_or_channel(event, sender) -> None:
    if not (config.get("ai_enabled") and config.get("ai_groups_enabled")):
        return
    ready, _ = _ai_ready()
    if not ready:
        return
    msg = event.message
    is_mention = bool(getattr(msg, "mentioned", False))
    reply_to_msg_id = (
        getattr(msg, "reply_to_msg_id", None)
        or getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)
    )
    is_reply = bool(event.is_reply or reply_to_msg_id)
    should_respond = False
    reason = ""
    if is_mention:
        should_respond = True
        reason = "mentioned"
    if not should_respond and is_reply:
        try:
            replied = await event.get_reply_message()
            if replied:
                replied_sender = replied.sender_id
                replied_out = getattr(replied, "out", False)
                if replied_sender == OWNER_ID or replied_out:
                    should_respond = True
                    reason = "reply_to_owner"
        except Exception as e:  # noqa: BLE001
            log.warning(f"[group-reply] get_reply_message failed: {e}")
    log.info(
        f"[group-msg] chat={event.chat_id} from={sender.id} "
        f"mentioned={is_mention} is_reply={is_reply} "
        f"decision={'REPLY' if should_respond else 'SKIP'}({reason})"
    )
    if not should_respond:
        return
    cooldown = int(config.get("group_cooldown", DEFAULT_GROUP_COOLDOWN))
    if cooldown > 0:
        key = f"g_{event.chat_id}_{sender.id}"
        now = time.time()
        last = replied_users.get(key, 0)
        if now - last < cooldown:
            log.debug(f"[group-cooldown] chat={event.chat_id} user={sender.id} skipping (within {cooldown}s)")
            return
        replied_users[key] = now
    session_id = f"group_{event.chat_id}"
    response_text = await _ai_respond(session_id, event.raw_text or "")
    if not response_text:
        return
    try:
        await event.reply(response_text)
        stats["replies_sent"] += 1
        log.info(f"Group reply in {event.chat_id} via AI ({reason})")
    except Exception as e:  # noqa: BLE001
        log.error(f"Group reply failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# ║                              Run                                  ║
# ═══════════════════════════════════════════════════════════════════
async def main():
    global OWNER_ID
    log.info("Connecting to Telegram...")
    await client.start(phone=PHONE)
    me = await client.get_me()
    OWNER_ID = me.id
    log.info(f"✅ Logged in: {me.first_name} (@{me.username}) — id={me.id}")

    ready, err_msg = _ai_ready()
    ai_info = f"🟢 ready ({config['ai_model']})" if ready else f"🔴 {err_msg}"

    print(
        "\n🌙 Bidar v" + VERSION + " is running!\n"
        f"   Name:     {me.first_name}\n"
        f"   Username: @{me.username}\n"
        f"   ID:       {me.id}\n"
        f"   UI Lang:  {config.get('bot_lang', 'en')} (use {CMD_PREFIX}botlang to switch)\n"
        f"   Commands: {CMD_PREFIX}help\n"
        f"   Online: {'🟢' if config['online_enabled'] else '🔴'}  "
        f"Auto-reply: {'🟢' if config['autoreply_enabled'] else '🔴'}  "
        f"AI: {'🟢' if config.get('ai_enabled') else '🔴'}\n"
        f"   AI: {ai_info}\n"
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
