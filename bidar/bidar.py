"""
Bidar — Bilingual Telegram Userbot with AI Assistant 🌙🤖
============================================================

Features:
  • Always-online (UpdateStatusRequest periodic)
  • Static & AI-powered auto-reply with per-chat context
  • Image generation, editing, OCR via Gemini
  • Universal music downloader (.sc — SoundCloud / YouTube / Spotify / Deezer / Apple Music / Tidal / Bandcamp ...)
  • Auto-detect music links in private chats & whitelisted groups
  • Translation (.tl, .to)
  • Bilingual UI (English + Persian) — switchable at runtime
  • Owner-only command lock with double safety check
  • Persistent JSON config

See `.help` for full command list.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.types import DocumentAttributeAudio

# Optional: AI integration via Emergent Universal Key
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # type: ignore
    AI_LIB_OK = True
except ImportError:
    AI_LIB_OK = False
    LlmChat = None  # type: ignore
    UserMessage = None  # type: ignore
    ImageContent = None  # type: ignore

# Optional: SoundCloud download via yt-dlp
try:
    import yt_dlp  # type: ignore
    YTDLP_OK = True
except ImportError:
    YTDLP_OK = False
    yt_dlp = None  # type: ignore

# ────────────────────────── Base config (.env) ──────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]
SESSION_NAME = os.environ.get("SESSION_NAME", "bidar_session")
CMD_PREFIX = os.environ.get("CMD_PREFIX", ".")
VERSION = "1.9.1"

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
    # Music (auto-detect & download from any platform)
    "music_enabled": True,
    # Whitelist of group/channel chat IDs where AI replies & music auto-detect are allowed.
    # Private chats are always allowed (independent of this list).
    "allowed_groups": [],
}

config: dict = copy.deepcopy(_DEFAULT_CONFIG)


def load_config() -> None:
    global config
    base = copy.deepcopy(_DEFAULT_CONFIG)
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
_sc_results: dict[int, list[dict]] = {}  # per-chat last SoundCloud search results
_music_recent: dict[str, float] = {}  # dedup: chat_id|url → timestamp

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
        "en": "💬 **AI in groups: {state}**\n\nℹ️ In groups, AI only replies when:\n  • The group is in the allowed list (`{p}allow list`)\n  • AND someone replies to your message or mentions you with @username\n\n🧠 Group conversation memory is preserved (until reset).",
        "fa": "💬 **AI در گروه‌ها: {state}**\n\nℹ️ در گروه فقط وقتی پاسخ میده که:\n  • گروه در لیست مجاز باشه (`{p}allow list`)\n  • و کسی روی پیامت ریپلای بزنه یا با @username منشنت کنه\n\n🧠 حافظه مکالمه گروه حفظ میشه (تا ریست کنی).",
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

    # SoundCloud
    "sc_usage": {
        "en": "🎵 **Universal Music Downloader**\n\n  `{p}sc <link>` — download from **any** music platform link\n     Supported: SoundCloud · YouTube · YouTube Music · Spotify · Deezer · Apple Music · Tidal · Bandcamp · Mixcloud · Yandex\n  `{p}sc <song name>` — search **SoundCloud** (top 5 results)\n  `{p}sc <1-5>` — download from last search results\n\n📝 Examples:\n  `{p}sc https://open.spotify.com/track/...`\n  `{p}sc https://music.apple.com/.../song/...`\n  `{p}sc shadmehr aghili setareh`\n\n🤖 Auto-detect is ON for **private chats** and any group in `{p}allow list`.",
        "fa": "🎵 **دانلودر موزیک از همه پلتفرم‌ها**\n\n  `{p}sc <لینک>` — دانلود از **هر** لینک موسیقی\n     پشتیبانی: ساندکلاد · یوتیوب · YouTube Music · اسپاتیفای · دیزر · اپل موزیک · تایدال · Bandcamp · Mixcloud · یاندکس\n  `{p}sc <اسم آهنگ>` — جستجو در **ساندکلاد** (۵ نتیجه)\n  `{p}sc <۱ تا ۵>` — دانلود از نتایج جستجوی قبلی\n\n📝 مثال:\n  `{p}sc https://open.spotify.com/track/...`\n  `{p}sc https://music.apple.com/.../song/...`\n  `{p}sc شادمهر عقیلی ستاره`\n\n🤖 تشخیص خودکار در **پی‌وی** و گروه‌های موجود در `{p}allow list` فعاله.",
    },
    "sc_lib_missing": {
        "en": "❌ `yt-dlp` is not installed.\n\n🔧 Install it:\n  `pip install yt-dlp`\nThen restart the bot.",
        "fa": "❌ کتابخونه `yt-dlp` نصب نیست.\n\n🔧 نصبش کن:\n  `pip install yt-dlp`\nبعد ربات رو ری‌استارت کن.",
    },
    "sc_searching": {"en": "🔎 Searching SoundCloud: _{q}_ ...", "fa": "🔎 در حال جستجو در ساندکلاد: _{q}_ ..."},
    "sc_no_results": {"en": "❌ No results found for: _{q}_", "fa": "❌ نتیجه‌ای برای _{q}_ پیدا نشد."},
    "sc_results": {
        "en": "🎵 **SoundCloud results for:** _{q}_\n\n{list}\n\n⬇️ To download, send: `{p}sc <number>`\nExample: `{p}sc 1`",
        "fa": "🎵 **نتایج ساندکلاد برای:** _{q}_\n\n{list}\n\n⬇️ برای دانلود بفرست: `{p}sc <شماره>`\nمثال: `{p}sc 1`",
    },
    "sc_no_pending": {
        "en": "❌ No previous search results in this chat. First search:\n`{p}sc <song name>`",
        "fa": "❌ نتیجه جستجوی قبلی توی این چت وجود نداره. اول جستجو کن:\n`{p}sc <اسم آهنگ>`",
    },
    "sc_invalid_pick": {"en": "⚠️ Pick a number between 1 and {n}.", "fa": "⚠️ یه عدد بین ۱ تا {n} انتخاب کن."},

    # Universal Music Downloader
    "music_downloading": {"en": "🎵 Downloading from {platform}...", "fa": "🎵 در حال دانلود از {platform}..."},
    "music_resolving":   {"en": "🔎 Resolving track from {platform} (DRM bypass via YouTube)...",
                          "fa": "🔎 شناسایی آهنگ از {platform} (به دلیل DRM، از یوتیوب می‌گیرم)..."},
    "music_uploading":   {"en": "📤 Uploading: _{title}_ ...", "fa": "📤 در حال آپلود: _{title}_ ..."},
    "music_failed":      {"en": "❌ {platform} download failed: `{e}`", "fa": "❌ دانلود از {platform} ناموفق بود: `{e}`"},
    "music_meta_failed": {
        "en": "❌ Couldn't read track info from {platform}. Try `{p}sc <song name>` instead.",
        "fa": "❌ اطلاعات آهنگ از {platform} خونده نشد. به‌جاش `{p}sc <اسم آهنگ>` رو امتحان کن.",
    },
    "music_caption":     {"en": "🎵 **{title}**\n👤 {artist}\n☁️ {platform}",
                          "fa": "🎵 **{title}**\n👤 {artist}\n☁️ {platform}"},

    # Music auto-detect toggle
    "music_set": {
        "en": "🎵 **Music auto-detect: {state}**\n\nℹ️ When ON, any music link sent in a private chat or whitelisted group is downloaded and replied as audio automatically.\n  • Private chats: always active\n  • Groups: only those in `{p}allow list`\n\nTo manage allowed groups: `{p}allow help`",
        "fa": "🎵 **تشخیص خودکار موزیک: {state}**\n\nℹ️ وقتی روشن باشه، هر لینک موسیقی که در پی‌وی یا گروه‌های مجاز فرستاده بشه، خودکار دانلود و به صورت فایل صوتی ریپلای میشه.\n  • پی‌وی: همیشه فعال\n  • گروه‌ها: فقط اونایی که در `{p}allow list` هستن\n\nمدیریت گروه‌های مجاز: `{p}allow help`",
    },

    # Allow list (unified whitelist for AI + Music in groups)
    "allow_help": {
        "en": "📋 **Allowed Groups (unified whitelist for AI + Music)**\n\n  `{p}allow add <chat_id>` — add a group\n  `{p}allow here` — add the **current** chat\n  `{p}allow remove <chat_id>` — remove a group\n  `{p}allow rmhere` — remove the **current** chat\n  `{p}allow list` — show all allowed groups\n  `{p}allow clear` — clear the list\n\n💡 Get a chat ID with `{p}id` inside the group.\n\nℹ️ This list controls **both**:\n  • AI replies in groups (requires `{p}aigroups on`)\n  • Music link auto-detect in groups (requires `{p}music on`)\n\nPrivate chats are always allowed and independent of this list.",
        "fa": "📋 **گروه‌های مجاز (لیست یکپارچه برای AI و موزیک)**\n\n  `{p}allow add <chat_id>` — اضافه کردن یه گروه\n  `{p}allow here` — اضافه کردن **همین** چت\n  `{p}allow remove <chat_id>` — حذف یه گروه\n  `{p}allow rmhere` — حذف **همین** چت\n  `{p}allow list` — نمایش لیست\n  `{p}allow clear` — پاک کردن همه\n\n💡 برای گرفتن chat ID داخل گروه دستور `{p}id` رو بزن.\n\nℹ️ این لیست **هم‌زمان** کنترل می‌کنه:\n  • پاسخ AI در گروه‌ها (نیازمند `{p}aigroups on`)\n  • تشخیص خودکار لینک موزیک در گروه‌ها (نیازمند `{p}music on`)\n\nچت‌های خصوصی همیشه مجازن و به این لیست بستگی ندارن.",
    },
    "allow_added":   {"en": "✅ Added `{cid}` to allowed groups. ({n} total)", "fa": "✅ `{cid}` به گروه‌های مجاز اضافه شد. (مجموع: {n})"},
    "allow_exists":  {"en": "ℹ️ `{cid}` is already in the allowed groups list.", "fa": "ℹ️ `{cid}` از قبل در لیست مجاز هست."},
    "allow_removed": {"en": "✅ Removed `{cid}` from allowed groups. ({n} left)", "fa": "✅ `{cid}` از لیست مجاز حذف شد. (باقی‌مونده: {n})"},
    "allow_notfound":{"en": "⚠️ `{cid}` is not in the allowed groups list.", "fa": "⚠️ `{cid}` در لیست مجاز نیست."},
    "allow_invalid": {"en": "⚠️ Invalid chat ID. Use a numeric ID (e.g., `-1001234567890`).", "fa": "⚠️ chat ID معتبر نیست. باید عددی باشه (مثلاً `-1001234567890`)."},
    "allow_list_empty": {"en": "📋 Allowed groups list is **empty**.\n\nAdd one with `{p}allow add <chat_id>` or `{p}allow here`.", "fa": "📋 لیست گروه‌های مجاز **خالیه**.\n\nبا `{p}allow add <chat_id>` یا `{p}allow here` اضافه کن."},
    "allow_list_title": {"en": "📋 **Allowed Groups** ({n}):\n\n{list}\n\nRemove with `{p}allow remove <chat_id>`", "fa": "📋 **گروه‌های مجاز** ({n}):\n\n{list}\n\nحذف با `{p}allow remove <chat_id>`"},
    "allow_cleared": {"en": "🗑 Cleared {n} group(s) from allowed list.", "fa": "🗑 {n} گروه از لیست مجاز پاک شد."},
    "allow_here_pv": {"en": "ℹ️ This is a private chat — private chats are always allowed.", "fa": "ℹ️ اینجا یه چت خصوصیه — چت‌های خصوصی همیشه مجازن."},

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
            "🎵 **Music (Universal Downloader)**\n"
            "  `{p}sc <link>` — download from **any** music platform link\n"
            "     (SoundCloud / YouTube / Spotify / Deezer / Apple Music / Tidal / Bandcamp ...)\n"
            "  `{p}sc <name>` — search SoundCloud (top 5) → pick with `{p}sc <num>`\n"
            "  `{p}music on|off` — toggle **auto-detect** of music links in chats\n"
            "  `{p}allow help` — manage groups allowed for AI & music auto-detect\n\n"
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
            "🎵 **موزیک (دانلودر جامع)**\n"
            "  `{p}sc <لینک>` — دانلود از **هر** لینک موسیقی\n"
            "     (ساندکلاد / یوتیوب / اسپاتیفای / دیزر / اپل موزیک / تایدال / Bandcamp ...)\n"
            "  `{p}sc <اسم>` — جستجو در ساندکلاد (۵ نتیجه) → انتخاب با `{p}sc <شماره>`\n"
            "  `{p}music on|off` — روشن/خاموش کردن **تشخیص خودکار** لینک موزیک\n"
            "  `{p}allow help` — مدیریت گروه‌های مجاز برای AI و دانلود خودکار\n\n"
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


# ────────── Music Helpers (Universal Downloader) ──────────
# Platform detection patterns. Order matters — first match wins.
_MUSIC_PLATFORMS: list[tuple[str, re.Pattern, bool]] = [
    # (name, regex, is_drm_protected)
    ("youtube",   re.compile(r"https?://(?:(?:www|m|music)\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/|playlist\?list=)|youtu\.be/)[\w\-]+(?:[?&][^\s]*)?", re.I), False),
    # Any subdomain (www / m / on.soundcloud.com mobile share-links) is valid
    ("soundcloud",re.compile(r"https?://(?:[\w-]+\.)?(?:soundcloud\.com|snd\.sc)/[\w\-/?=&%.#]+", re.I), False),
    ("bandcamp",  re.compile(r"https?://[\w\-]+\.bandcamp\.com/(?:track|album)/[\w\-]+", re.I), False),
    ("mixcloud",  re.compile(r"https?://(?:www\.)?mixcloud\.com/[\w\-]+/[\w\-]+/?", re.I), False),
    ("vimeo",     re.compile(r"https?://(?:www\.)?vimeo\.com/\d+", re.I), False),
    ("yandex",    re.compile(r"https?://music\.yandex\.\w+/album/\d+/track/\d+", re.I), False),
    # DRM-protected (download via YouTube fallback)
    ("spotify",   re.compile(r"https?://open\.spotify\.com/(?:intl-\w+/)?track/[\w]+", re.I), True),
    ("deezer",    re.compile(r"https?://(?:www\.)?deezer\.com/(?:\w+/)?track/\d+", re.I), True),
    ("apple",     re.compile(r"https?://music\.apple\.com/[\w\-/]+/(?:song|album)/[^\s?]+(?:\?i=\d+)?", re.I), True),
    ("tidal",     re.compile(r"https?://(?:(?:listen|www)\.)?tidal\.com/(?:browse/)?track/\d+", re.I), True),
    # Short share-links (resolved to canonical URLs before download)
    ("spotify",   re.compile(r"https?://spotify\.link/[\w]+", re.I), True),
    ("deezer",    re.compile(r"https?://(?:deezer\.page\.link|link\.deezer\.com)/[\w]+", re.I), True),
]

_PLATFORM_LABEL = {
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "bandcamp": "Bandcamp",
    "mixcloud": "Mixcloud",
    "vimeo": "Vimeo",
    "yandex": "Yandex Music",
    "spotify": "Spotify",
    "deezer": "Deezer",
    "apple": "Apple Music",
    "tidal": "Tidal",
}


def _detect_music_url(text: str) -> tuple[str, str, bool] | None:
    """Scan text for the first known music URL.
    Returns (platform_name, url, is_drm) or None.
    """
    if not text:
        return None
    for name, rx, is_drm in _MUSIC_PLATFORMS:
        m = rx.search(text)
        if m:
            return name, m.group(0), is_drm
    return None


# Short share-links that must be resolved to a canonical URL before metadata
# extraction (DRM platforms). SoundCloud's on.soundcloud.com links are handled
# natively by yt-dlp and need no resolution.
_SHORTLINK_RE = re.compile(
    r"https?://(?:spotify\.link|deezer\.page\.link|link\.deezer\.com)/", re.I)


def _resolve_redirect(url: str) -> str:
    """Follow HTTP redirects and return the final URL. Blocking — run in a thread."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                if method == "GET":
                    resp.read(1024)
                return resp.url or url
        except Exception as e:  # noqa: BLE001
            log.debug(f"[music] redirect resolve ({method}) failed: {e}")
    return url


# ────────── Whitelist helpers (unified for AI + Music) ──────────
def _chat_id_variants(cid) -> set[int]:
    """All equivalent representations of a Telegram chat ID.

    `.id`-style raw positive IDs (`2453861964`), marked supergroup IDs
    (`-1002453861964`) and legacy negative group IDs (`-456789`) all map to
    the same set, so whitelist checks match regardless of the stored form.
    """
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return set()
    raw = abs(cid)
    variants = {cid, raw, -raw}
    s = str(raw)
    if s.startswith("100") and len(s) > 6:
        bare = int(s[3:])
        variants |= {bare, -bare}
    else:
        variants.add(int("-100" + s))
    return variants


def _is_chat_allowed(chat_id) -> bool:
    """True if `chat_id` (in any representation) is in the allowed_groups whitelist."""
    allowed = config.get("allowed_groups", []) or []
    if not allowed:
        return False
    variants = _chat_id_variants(chat_id)
    return any(int(a) in variants for a in allowed)


def _whitelist_contains(cid, lst) -> bool:
    variants = _chat_id_variants(cid)
    return any(int(x) in variants for x in lst)


def _whitelist_without(cid, lst) -> list:
    variants = _chat_id_variants(cid)
    return [x for x in lst if int(x) not in variants]


def _fmt_duration(seconds) -> str:
    """Format track duration as M:SS or H:MM:SS."""
    if not seconds:
        return "?:??"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fetch_drm_metadata(url: str, platform: str) -> str | None:
    """For DRM-protected platforms (Spotify, Deezer, Apple Music, Tidal),
    fetch track metadata and return a search query of the form 'Artist - Title'.
    Returns None on failure.

    Uses public oEmbed / embed endpoints where available (bot-friendly), with
    OpenGraph meta parsing as a fallback.
    """
    # ── Strategy 1: oEmbed (Spotify) — public, no auth, returns track name ──
    if platform == "spotify":
        try:
            req = urllib.request.Request(
                "https://open.spotify.com/oembed?url=" + urllib.parse.quote(url, safe=":/?=&"),
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read(50_000).decode("utf-8", errors="ignore"))
            title = (data.get("title") or "").strip()
            # oEmbed only gives title, fall through to embed page for artist
            artist = ""
            try:
                emb_url = data.get("iframe_url") or (
                    "https://open.spotify.com/embed/track/" + url.rstrip("/").split("/")[-1].split("?")[0]
                )
                req2 = urllib.request.Request(emb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req2, timeout=15) as resp2:
                    page = resp2.read(200_000).decode("utf-8", errors="ignore")
                m = re.search(r'"artists":\s*\[\s*\{\s*"name"\s*:\s*"([^"]+)"', page)
                if m:
                    artist = m.group(1).strip()
                if not title:
                    m2 = re.search(r'"name"\s*:\s*"([^"]+)"', page)
                    if m2:
                        title = m2.group(1).strip()
            except Exception as e:  # noqa: BLE001
                log.debug(f"[music] Spotify embed parse: {e}")
            if artist and title:
                return f"{artist} - {title}"
            if title:
                return title
        except Exception as e:  # noqa: BLE001
            log.warning(f"[music] Spotify oEmbed failed: {e}")

    # ── Strategy 2: OpenGraph meta tags from main URL (Deezer / Apple / Tidal) ──
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read(300_000).decode("utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        log.warning(f"[music] DRM metadata fetch failed ({platform}): {e}")
        return None

    def _meta(prop: str) -> str:
        # Match both orderings: property=...content=...  AND  content=...property=...
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
            html, re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    og_title = _meta("og:title")
    og_desc = _meta("og:description")
    music_musician = _meta("music:musician") or _meta("music:musician_description")

    # `music:musician` is often a URL on Deezer — discard it in that case
    if music_musician and re.match(r"^https?://", music_musician):
        music_musician = ""

    title = og_title
    artist = music_musician

    # Try to extract artist from og:description when not available directly
    if not artist and og_desc:
        # Spotify: "Listen to TITLE on Spotify. ARTIST · Song · YEAR"
        m = re.search(r"on (?:Spotify|Deezer|Apple Music|Tidal)\.\s*([^·•]+?)(?:\s*[·•]|$)",
                      og_desc, re.IGNORECASE)
        if m:
            artist = m.group(1).strip()
        else:
            # Deezer / generic: "Listen to TITLE by ARTIST on Deezer"
            m = re.search(r"\bby\s+(.+?)(?:\s+on\s+|\s+from\s+|$)", og_desc, re.IGNORECASE)
            if m:
                artist = m.group(1).strip()
            else:
                # Dot/bullet/dash separated lists:
                #   "Song · ARTIST · YEAR"  (Apple Music)
                #   "ARTIST - song - YEAR" (Deezer)
                generic = re.compile(
                    r"^(?:song|album|track|playlist|ep|single|"
                    r"spotify|deezer|apple\s*music|tidal|"
                    r"listen\s*to|year)$",
                    re.IGNORECASE,
                )
                year_rx = re.compile(r"^\d{4}$")
                # Split on bullets OR space-dash-space (but not unicode dashes inside names)
                parts = [p.strip() for p in re.split(r"\s*[·•]\s*|\s+-\s+", og_desc) if p.strip()]
                parts = [p for p in parts if not generic.match(p) and not year_rx.match(p)]
                if parts:
                    artist = parts[0]

    artist = (artist or "").strip().strip("-—–·")
    title = (title or "").strip().strip("-—–·")
    # Strip trailing platform suffix sometimes present in titles
    title = re.sub(r"\s*[-–|]\s*(Spotify|Deezer|Apple Music|Tidal)\s*$", "", title, flags=re.I)

    if artist and title:
        return f"{artist} - {title}"
    if title:
        return title
    return None


def _sc_search_sync(query: str) -> list[dict]:
    """Search SoundCloud (top 5). Blocking — run in a thread."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"scsearch5:{query}", download=False)
    results = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        url = e.get("url") or e.get("webpage_url")
        if not url:
            continue
        results.append({
            "title": e.get("title") or "Unknown",
            "url": url,
            "duration": e.get("duration"),
            "uploader": e.get("uploader") or e.get("channel") or "",
        })
    return results


def _music_download_sync(target: str, tmpdir: str, is_search: bool = False) -> dict | None:
    """Download audio from any platform supported by yt-dlp.

    `target` can be:
      • a direct URL (SoundCloud / YouTube / Bandcamp / Mixcloud / ...)
      • a `ytsearch1:` query string (used as fallback for DRM platforms)

    Always returns mp3 when ffmpeg is available, otherwise the best progressive audio.
    """
    have_ffmpeg = shutil.which("ffmpeg") is not None
    opts = {
        "format": "bestaudio[ext=mp3]/bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "%(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        # Cap downloads at a sane size to protect Telegram upload limits & disk
        "max_filesize": 100 * 1024 * 1024,  # 100MB
    }
    if have_ffmpeg:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=True)
    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else None
    if not info:
        return None
    audio_exts = {".mp3", ".m4a", ".opus", ".ogg", ".aac", ".wav", ".flac"}
    filepath = None
    for name in os.listdir(tmpdir):
        if os.path.splitext(name)[1].lower() in audio_exts:
            filepath = os.path.join(tmpdir, name)
            break
    if not filepath:
        return None
    # Cover art for Telegram audio thumbnail
    thumb_path = None
    thumb_url = info.get("thumbnail") or ""
    if thumb_url.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        try:
            thumb_path = os.path.join(tmpdir, "cover.jpg")
            urllib.request.urlretrieve(thumb_url, thumb_path)
        except Exception:  # noqa: BLE001
            thumb_path = None
    return {
        "filepath": filepath,
        "title": info.get("title") or "Unknown",
        "uploader": info.get("uploader") or info.get("channel") or info.get("artist") or "",
        "duration": int(info.get("duration") or 0),
        "thumb": thumb_path,
        "source_url": info.get("webpage_url") or "",
    }


async def _music_download_and_send(event, url: str, platform: str, is_drm: bool, *,
                                   reply_to_msg_id=None, force_reply: bool = False) -> bool:
    """Download a track from any platform and send it as audio.

    For DRM platforms (Spotify/Deezer/Apple Music/Tidal), extracts metadata then
    searches YouTube → SoundCloud for the actual audio.

    Returns True on success.
    `reply_to_msg_id` overrides the default reply target (used by auto-detect handler).
    `force_reply=True` makes the status message a reply even for the owner's own
    messages (auto-detect on outgoing links must never edit the original message).
    """
    label = _PLATFORM_LABEL.get(platform, platform.capitalize())
    # `.sc` command flow edits the command message; auto-detect always replies.
    is_owned = bool(getattr(event, "out", False)) and not force_reply
    status_msg = None
    tmpdir = None
    try:
        if is_owned:
            status_msg = await event.edit(t("music_downloading", platform=label))
        else:
            status_msg = await event.reply(t("music_downloading", platform=label))

        # Short share-links (spotify.link, deezer.page.link, …) → resolve to the
        # canonical URL first so platform detection & metadata extraction work.
        if _SHORTLINK_RE.match(url):
            final = await asyncio.to_thread(_resolve_redirect, url)
            if final and final != url:
                redetected = _detect_music_url(final)
                if redetected:
                    platform, url, is_drm = redetected
                    label = _PLATFORM_LABEL.get(platform, platform.capitalize())
                else:
                    url = final

        # DRM: extract metadata first, then search YouTube → SoundCloud fallback
        if is_drm:
            try:
                await status_msg.edit(t("music_resolving", platform=label))
            except Exception:  # noqa: BLE001
                pass
            query = await asyncio.to_thread(_fetch_drm_metadata, url, platform)
            if not query:
                await status_msg.edit(t("music_meta_failed", platform=label, p=CMD_PREFIX))
                return False
            log.info(f"[music] DRM {platform} → search query: {query}")
            # YouTube first (most accurate match). Server/datacenter IPs are
            # often blocked by YouTube (HTTP 403), so also queue the top
            # SoundCloud results — DRM-protected (Go+ preview) entries raise
            # and the loop simply moves on to the next candidate.
            targets = [f"ytsearch1:{query}"]
            try:
                sc_results = await asyncio.to_thread(_sc_search_sync, query)
                targets += [r["url"] for r in sc_results[:3]]
            except Exception as e:  # noqa: BLE001
                log.warning(f"[music] SoundCloud fallback search failed: {e}")
                targets.append(f"scsearch1:{query}")
        else:
            targets = [url]

        info = None
        last_err: Exception | None = None
        for tgt in targets:
            tmpdir = tempfile.mkdtemp(prefix="bidar_music_")
            try:
                info = await asyncio.to_thread(_music_download_sync, tgt, tmpdir)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning(f"[music] download failed for target `{tgt[:80]}`: {e}")
                info = None
            if info:
                break
            shutil.rmtree(tmpdir, ignore_errors=True)
            tmpdir = None

        if not info:
            err = str(last_err)[:200] if last_err else "no audio found"
            await status_msg.edit(t("music_failed", platform=label, e=err))
            return False

        try:
            await status_msg.edit(t("music_uploading", title=info["title"][:80]))
        except Exception:  # noqa: BLE001
            pass
        attrs = [DocumentAttributeAudio(
            duration=info["duration"],
            title=info["title"][:60],
            performer=(info["uploader"] or label)[:60],
        )]
        send_reply_to = reply_to_msg_id if reply_to_msg_id is not None else getattr(event, "reply_to_msg_id", None)
        if send_reply_to is None and not is_owned:
            # Auto-detect path: reply to the incoming message
            send_reply_to = event.message.id
        await client.send_file(
            event.chat_id,
            info["filepath"],
            caption=t("music_caption",
                      title=info["title"][:200],
                      artist=info["uploader"] or "—",
                      platform=label),
            attributes=attrs,
            thumb=info["thumb"],
            reply_to=send_reply_to,
        )
        try:
            await status_msg.delete()
        except Exception:  # noqa: BLE001
            pass
        log.info(f"[music] sent ({platform}): {info['title']}")
        return True
    except Exception as e:  # noqa: BLE001
        log.error(f"[music] download/send failed ({platform}): {e}")
        if status_msg is not None:
            try:
                await status_msg.edit(t("music_failed", platform=label, e=str(e)[:200]))
            except Exception:  # noqa: BLE001
                pass
        return False
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# Backwards-compatible alias: existing call sites still use _sc_download_and_send
async def _sc_download_and_send(event, url: str) -> None:
    await _music_download_and_send(event, url, "soundcloud", False)


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
    await event.edit(t("aigroups_set", state=_state_label(new), p=CMD_PREFIX))


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


# ═════════ Universal Music Downloader (any platform) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}sc(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_soundcloud(event):
    """Universal music downloader.
    - `.sc <link>` — any supported platform (SoundCloud, YouTube, Spotify, Deezer, Apple Music, Tidal, Bandcamp, …)
    - `.sc <query>` — search SoundCloud (top 5)
    - `.sc <1-5>` — pick from last search results
    """
    arg = event.pattern_match.group(1)
    if not arg or not arg.strip():
        await event.edit(t("sc_usage", p=CMD_PREFIX))
        return
    if not YTDLP_OK:
        await event.edit(t("sc_lib_missing"))
        return
    arg = arg.strip()
    chat_id = event.chat_id

    # Case 1: pick a number from the last search results
    if arg.isdigit():
        results = _sc_results.get(chat_id)
        if not results:
            await event.edit(t("sc_no_pending", p=CMD_PREFIX))
            return
        idx = int(arg)
        if not (1 <= idx <= len(results)):
            await event.edit(t("sc_invalid_pick", n=len(results)))
            return
        await _music_download_and_send(event, results[idx - 1]["url"], "soundcloud", False)
        return

    # Case 2: any supported music platform URL
    detected = _detect_music_url(arg)
    if detected:
        platform, url, is_drm = detected
        await _music_download_and_send(event, url, platform, is_drm)
        return

    # Case 3: search by song name → show top 5 SoundCloud results
    msg = await event.edit(t("sc_searching", q=arg[:100]))
    try:
        results = await asyncio.to_thread(_sc_search_sync, arg)
    except Exception as e:  # noqa: BLE001
        log.error(f"[.sc] search failed: {e}")
        await msg.edit(t("music_failed", platform="SoundCloud", e=str(e)[:200]))
        return
    if not results:
        await msg.edit(t("sc_no_results", q=arg[:100]))
        return
    _sc_results[chat_id] = results
    lines = []
    for i, r in enumerate(results, 1):
        dur = _fmt_duration(r["duration"])
        up = f" — {r['uploader']}" if r["uploader"] else ""
        lines.append(f"**{i}.** {r['title']}{up}  `[{dur}]`")
    await msg.edit(t("sc_results", q=arg[:100], list="\n".join(lines), p=CMD_PREFIX))


# ═════════ Music auto-detect toggle ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}music(?:\s+(on|off|روشن|خاموش))?$"))
@owner_only
async def cmd_music(event):
    arg = event.pattern_match.group(1)
    new = _parse_on_off(
        None if arg is None else ("on" if arg in {"on", "روشن"} else "off"),
        config.get("music_enabled", True),
    )
    config["music_enabled"] = new
    save_config()
    await event.edit(t("music_set", state=_state_label(new), p=CMD_PREFIX))


# ═════════ Allowed groups whitelist (unified for AI + Music) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}allow(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_allow(event):
    """Manage the unified whitelist of allowed groups for AI replies and music auto-detect."""
    arg = (event.pattern_match.group(1) or "").strip()
    parts = arg.split(maxsplit=1) if arg else []
    sub = (parts[0].lower() if parts else "")
    rest = parts[1].strip() if len(parts) > 1 else ""

    allowed = list(config.get("allowed_groups", []) or [])

    def _save_and_set(new_list):
        config["allowed_groups"] = new_list
        save_config()

    # No arg or "help"
    if not sub or sub == "help":
        await event.edit(t("allow_help", p=CMD_PREFIX))
        return

    # `.allow list`
    if sub in {"list", "ls", "show"}:
        if not allowed:
            await event.edit(t("allow_list_empty", p=CMD_PREFIX))
            return
        body = "\n".join(f"  • `{cid}`" for cid in allowed)
        await event.edit(t("allow_list_title", n=len(allowed), list=body, p=CMD_PREFIX))
        return

    # `.allow clear`
    if sub in {"clear", "reset"}:
        n = len(allowed)
        _save_and_set([])
        await event.edit(t("allow_cleared", n=n))
        return

    # `.allow here` — add current chat
    if sub == "here":
        if event.is_private:
            await event.edit(t("allow_here_pv"))
            return
        cid = int(event.chat_id)
        if _whitelist_contains(cid, allowed):
            await event.edit(t("allow_exists", cid=cid))
            return
        allowed.append(cid)
        _save_and_set(allowed)
        await event.edit(t("allow_added", cid=cid, n=len(allowed)))
        return

    # `.allow rmhere` — remove current chat
    if sub == "rmhere":
        cid = int(event.chat_id)
        if not _whitelist_contains(cid, allowed):
            await event.edit(t("allow_notfound", cid=cid))
            return
        allowed = _whitelist_without(cid, allowed)
        _save_and_set(allowed)
        await event.edit(t("allow_removed", cid=cid, n=len(allowed)))
        return

    # `.allow add <id>` — any ID form is accepted (raw `.id` output, -100-marked, …)
    if sub in {"add", "+"}:
        try:
            cid = int(rest)
        except (TypeError, ValueError):
            await event.edit(t("allow_invalid"))
            return
        if _whitelist_contains(cid, allowed):
            await event.edit(t("allow_exists", cid=cid))
            return
        allowed.append(cid)
        _save_and_set(allowed)
        await event.edit(t("allow_added", cid=cid, n=len(allowed)))
        return

    # `.allow remove <id>` / `.allow del <id>` / `.allow -`
    if sub in {"remove", "rm", "del", "delete", "-"}:
        try:
            cid = int(rest)
        except (TypeError, ValueError):
            await event.edit(t("allow_invalid"))
            return
        if not _whitelist_contains(cid, allowed):
            await event.edit(t("allow_notfound", cid=cid))
            return
        allowed = _whitelist_without(cid, allowed)
        _save_and_set(allowed)
        await event.edit(t("allow_removed", cid=cid, n=len(allowed)))
        return

    # Unknown subcommand → show help
    await event.edit(t("allow_help", p=CMD_PREFIX))


# ═════════ Info commands ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}stats$"))
@owner_only
async def cmd_stats(event):
    uptime = time.time() - stats["start_time"]
    interval = int(config.get("online_refresh_interval", DEFAULT_ONLINE_INTERVAL))
    ready, ai_err = _ai_ready()
    ai_state = t("on") if (config.get("ai_enabled") and ready) else t("off")
    music_state = t("on") if config.get("music_enabled", True) else t("off")
    allowed = config.get("allowed_groups", []) or []
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
        f"🎵 Music auto-detect: `{music_state}`\n"
        f"📋 Allowed groups: `{len(allowed)}`\n\n"
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
    # Show the marked chat ID (the exact form Telethon events use) so it can be
    # passed to `.allow add` directly.
    out = t("id_chat", id=event.chat_id)
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
    if OWNER_ID is not None and getattr(sender, "id", None) == OWNER_ID:
        return
    # Music auto-detect (private chats always + whitelisted groups). Also covers
    # links posted by bots/channels in groups. Runs in the background so it
    # never blocks the AI/auto-reply flow.
    asyncio.create_task(_maybe_handle_music_link(event, sender))
    if sender is None or getattr(sender, "bot", False):
        return
    if event.is_private:
        await _handle_private(event, sender)
    else:
        await _handle_group_or_channel(event, sender)


# Status/system messages the bot itself sends start with one of these markers —
# the outgoing music handler must never re-process them.
_BOT_MSG_PREFIXES = ("🎵", "🔎", "📤", "❌", "✅", "⚠️", "ℹ️", "📋")


@client.on(events.NewMessage(outgoing=True))
async def handle_outgoing_music(event):
    """Music auto-detect for the owner's own messages (PV + whitelisted groups)."""
    text = event.raw_text or ""
    if not text or text.startswith(CMD_PREFIX) or text.startswith(_BOT_MSG_PREFIXES):
        return
    asyncio.create_task(_maybe_handle_music_link(event, None))


async def _maybe_handle_music_link(event, sender) -> None:
    """Auto-detect music links in messages and reply with the downloaded audio."""
    if not config.get("music_enabled", True):
        return
    if not YTDLP_OK:
        return
    text = event.raw_text or ""
    if not text:
        return
    detected = _detect_music_url(text)
    if not detected:
        return
    platform, url, is_drm = detected

    # Authorization scope:
    #   - private chats: always allowed
    #   - groups/channels: only if the chat is in the allowed_groups whitelist
    #     (any ID representation — raw, -100-marked or legacy — matches)
    if not event.is_private:
        if not _is_chat_allowed(event.chat_id):
            log.info(f"[music-auto] skip — chat {event.chat_id} not in whitelist")
            return

    # Per-chat dedup: ignore the same URL within 5 minutes
    dedup_key = f"{event.chat_id}|{url}"
    now = time.time()
    last = _music_recent.get(dedup_key, 0)
    if now - last < 300:
        return
    _music_recent[dedup_key] = now
    # GC old entries
    if len(_music_recent) > 200:
        cutoff = now - 1800
        for k in list(_music_recent.keys()):
            if _music_recent[k] < cutoff:
                _music_recent.pop(k, None)

    log.info(
        f"[music-auto] {platform} link in chat={event.chat_id} from={getattr(sender,'id','self')} "
        f"drm={is_drm} url={url}"
    )
    ok = False
    try:
        ok = await _music_download_and_send(event, url, platform, is_drm,
                                            reply_to_msg_id=event.message.id,
                                            force_reply=True)
    except Exception as e:  # noqa: BLE001
        log.error(f"[music-auto] handler failed: {e}")
    finally:
        if not ok:
            # Allow retrying the same link right after a failure
            _music_recent.pop(dedup_key, None)


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
    # Whitelist: AI in groups only responds in chats present in `allowed_groups`.
    # If the list is empty, AI in groups is effectively disabled.
    if not _is_chat_allowed(event.chat_id):
        log.debug(f"[group-ai] skip — chat {event.chat_id} not in whitelist")
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
