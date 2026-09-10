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
import html
import io
import json
import logging
import logging.handlers
import mimetypes
import os
import platform
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
from telethon.tl.types import DocumentAttributeAudio, InputMessagesFilterDocument

# Optional: AI integration via Emergent Universal Key
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # type: ignore
    AI_LIB_OK = True
except ImportError:
    AI_LIB_OK = False
    LlmChat = None  # type: ignore
    UserMessage = None  # type: ignore
    ImageContent = None  # type: ignore

# Optional: PDF text extraction (.ask)
try:
    import pypdf  # type: ignore
    PDF_LIB_OK = True
except ImportError:
    PDF_LIB_OK = False
    pypdf = None  # type: ignore

# Optional: Word (.docx) text extraction (.ask)
try:
    import docx  # type: ignore  (python-docx)
    DOCX_LIB_OK = True
except ImportError:
    DOCX_LIB_OK = False
    docx = None  # type: ignore

# Optional: server resource metrics (.server)
try:
    import psutil  # type: ignore
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False
    psutil = None  # type: ignore

# Optional: Text-to-Speech via Emergent Universal Key (OpenAI TTS)
try:
    from emergentintegrations.llm.openai import OpenAITextToSpeech  # type: ignore
    TTS_LIB_OK = True
except ImportError:
    TTS_LIB_OK = False
    OpenAITextToSpeech = None  # type: ignore

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
VERSION = "1.21.0"

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
    # Default aspect ratio for .img / .imgedit (see SUPPORTED_AR for valid values).
    "image_aspect_ratio": "1:1",
    # Text-to-speech (.say)
    "tts_voice": "nova",
    "tts_model": "tts-1-hd",
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
        logging.handlers.RotatingFileHandler(
            BASE_DIR / "bidar.log", encoding="utf-8",
            maxBytes=5 * 1024 * 1024, backupCount=2,
        ),
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
        "en": "🌐 **Translation — auto fa↔en**\n\n  `{p}tl <text>` — Persian→English, anything else→Persian\n  `{p}tl <lang> <text>` — explicit target (e.g. `{p}tl arabic hello`)\n  reply + `{p}tl` — auto-translate replied message\n  reply + `{p}tl <lang>` — translate replied message to `<lang>`\n\n🌍 Languages: English/Persian names or ISO codes — `english`, `فارسی`, `arabic`, `عربی`, `spanish`, `اسپانیایی`, `french`, `فرانسوی`, `german`, `آلمانی`, `italian`, `russian`, `turkish`, `ترکی`, `japanese`, `ژاپنی`, `chinese`, `چینی`, `korean`, `کره‌ای`, `hindi`, `هندی`, `urdu`, `kurdish`, `کردی`, `dutch`, `portuguese`, `swedish`, `polish` ...",
        "fa": "🌐 **ترجمه — تشخیص خودکار فارسی↔انگلیسی**\n\n  `{p}tl <متن>` — فارسی→انگلیسی، هر زبون دیگه→فارسی\n  `{p}tl <زبون> <متن>` — مقصد دستی (مثلاً `{p}tl عربی سلام`)\n  ریپلای + `{p}tl` — ترجمه خودکار پیام ریپلای‌شده\n  ریپلای + `{p}tl <زبون>` — ترجمه پیام ریپلای‌شده به اون زبون\n\n🌍 زبون‌های پشتیبانی‌شده (فارسی یا انگلیسی یا کد ISO): `انگلیسی`, `فارسی`, `عربی`, `اسپانیایی`, `فرانسوی`, `آلمانی`, `ایتالیایی`, `روسی`, `ترکی`, `ترکی استانبولی`, `ژاپنی`, `چینی`, `کره‌ای`, `هندی`, `اردو`, `کردی`, `آذری`, `هلندی`, `پرتغالی`, `سوئدی`, `لهستانی`, `یونانی`, `عبری`, `ویتنامی`, `تایلندی`, `اندونزیایی` ...",
    },
    "tl_processing": {"en": "🌐 Translating...", "fa": "🌐 در حال ترجمه..."},
    "tl_result": {"en": "🌐 **Translation ({t}):**\n\n{txt}", "fa": "🌐 **ترجمه ({t}):**\n\n{txt}"},
    "tl_failed": {"en": "❌ Translation failed. Check AI status.", "fa": "❌ ترجمه ناموفق بود. AI رو چک کن."},
    "to_processing": {"en": "✏️ Translating...", "fa": "✏️ در حال ترجمه..."},
    "to_failed": {"en": "{txt}\n\n❌ Translation failed.", "fa": "{txt}\n\n❌ ترجمه ناموفق بود."},

    # Image
    "img_usage": {
        "en": "🎨 **Image generation**\n\n  `{p}img <description>`\n  `{p}img --ar 16:9 <description>` — override aspect ratio\n  `{p}img --portrait <description>` — friendly alias\n\n📝 Examples:\n  `{p}img a fluffy cat astronaut on Mars`\n  `{p}img --16:9 cinematic shot of a dragon over Tehran`\n  `{p}img --story a minimalist watercolor of mountains`\n\n🎯 Current model: `{m}`\n📐 Current aspect ratio: `{ar}` (`{p}imgsize` to change)",
        "fa": "🎨 **تولید تصویر**\n\n  `{p}img <توضیح تصویر>`\n  `{p}img --ar 16:9 <توضیح>` — تغییر ابعاد برای همین تصویر\n  `{p}img --استوری <توضیح>` — نام دوستانه\n\n📝 مثال:\n  `{p}img a fluffy cat astronaut on Mars`\n  `{p}img --16:9 نمای سینمایی از اژدها روی تهران`\n  `{p}img --استوری نقاشی مینیمال از کوه‌های دماوند`\n\n🎯 مدل فعلی: `{m}`\n📐 ابعاد فعلی: `{ar}` (با `{p}imgsize` عوض کن)",
    },
    "img_processing": {"en": "🎨 Generating image ({ar})...\n_{p}_",
                        "fa": "🎨 در حال تولید تصویر ({ar})...\n_{p}_"},
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

    # Image aspect ratio
    "imgsize_show": {
        "en": "📐 **Image aspect ratio:** `{ar}`\n\n🌟 Supported:\n  `1:1` square · `16:9` landscape · `9:16` portrait / story\n  `4:3` classic · `3:4` tall · `21:9` cinematic\n  `3:2`, `2:3`, `5:4`, `4:5`, `4:1`, `1:4`, `8:1`, `1:8`\n\n🪄 Friendly aliases (Persian/English):\n  `square / مربعی` · `landscape / افقی` · `portrait / عمودی`\n  `story / استوری` · `cinematic / سینمایی` · `photo / عکس`\n\n📝 Examples:\n  `{p}imgsize 16:9`\n  `{p}imgsize portrait`\n  `{p}imgsize استوری`\n\n💡 Per-image override (no permanent change):\n  `{p}img --ar 9:16 <prompt>` or `{p}img --landscape <prompt>`",
        "fa": "📐 **ابعاد تصویر:** `{ar}`\n\n🌟 ابعاد پشتیبانی‌شده:\n  `1:1` مربعی · `16:9` افقی · `9:16` عمودی/استوری\n  `4:3` کلاسیک · `3:4` بلند · `21:9` سینمایی\n  `3:2`, `2:3`, `5:4`, `4:5`, `4:1`, `1:4`, `8:1`, `1:8`\n\n🪄 نام‌های دوستانه (فارسی/انگلیسی):\n  `مربعی / square` · `افقی / landscape` · `عمودی / portrait`\n  `استوری / story` · `سینمایی / cinematic` · `عکس / photo`\n\n📝 مثال:\n  `{p}imgsize 16:9`\n  `{p}imgsize portrait`\n  `{p}imgsize استوری`\n\n💡 برای یک عکس خاص بدون تغییر پیش‌فرض:\n  `{p}img --ar 9:16 <prompt>` یا `{p}img --استوری <prompt>`",
    },
    "imgsize_set": {
        "en": "✅ Image aspect ratio set to `{ar}`.",
        "fa": "✅ ابعاد تصویر روی `{ar}` تنظیم شد.",
    },
    "imgsize_invalid": {
        "en": "⚠️ Invalid aspect ratio `{a}`.\nUse one of: `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `21:9`, `3:2`, `2:3`, `5:4`, `4:5`, `4:1`, `1:4`, `8:1`, `1:8`\nor a friendly alias: `square`, `landscape`, `portrait`, `story`, `cinematic`, `photo`, `مربعی`, `افقی`, `عمودی`, `استوری`, `سینمایی`, `عکس`.",
        "fa": "⚠️ ابعاد `{a}` معتبر نیست.\nیکی از این‌ها رو استفاده کن: `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `21:9`, `3:2`, `2:3`, `5:4`, `4:5`, `4:1`, `1:4`, `8:1`, `1:8`\nیا نام‌های دوستانه: `square`, `landscape`, `portrait`, `story`, `cinematic`, `photo`, `مربعی`, `افقی`, `عمودی`, `استوری`, `سینمایی`, `عکس`.",
    },

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

    # .mix — combine two images
    "mix_need_two": {
        "en": "🎭 **Combine two images**\n\nProvide **two** images one of these ways:\n1. **Reply** to one image and **attach** a second image to your `{p}mix` message.\n2. **Reply** to an album (2 photos sent together) with `{p}mix`.\n\n📝 Optional prompt:\n  `{p}mix put them both on a beach at sunset`\n  `{p}mix --16:9 blend into a movie poster`\n\nWithout a prompt, the two images are blended automatically.",
        "fa": "🎭 **ترکیب دو عکس**\n\nدو تا عکس رو یکی از این دو راه بده:\n۱. روی یه عکس **ریپلای** بزن و یه عکس دوم رو هم به پیام `{p}mix` **الصاق** کن.\n۲. روی یه آلبوم (دو عکسی که با هم فرستادی) با `{p}mix` ریپلای بزن.\n\n📝 پرامپت اختیاری:\n  `{p}mix هر دو رو کنار هم توی ساحل غروب بذار`\n  `{p}mix --16:9 به شکل پوستر فیلم ترکیبشون کن`\n\nبدون پرامپت، دو عکس خودکار با هم ترکیب می‌شن.",
    },
    "mix_processing": {"en": "🎭 Combining images...", "fa": "🎭 در حال ترکیب عکس‌ها..."},
    "mix_caption": {"en": "🎭 **Combined:** {p}", "fa": "🎭 **ترکیب‌شده:** {p}"},
    "mix_caption_default": {"en": "🎭 Combined image", "fa": "🎭 عکس ترکیب‌شده"},

    # .ask — Document Q&A (PDF / text files)
    "ask_usage": {
        "en": "📄 **Ask a document**\n\n1. **Reply** to a PDF, Word (.docx) or text file with `{p}ask` to analyse it.\n2. Then ask anything: `{p}ask what are the key points?`\n\n💡 You can also ask right away: reply to a file with `{p}ask summarise this`.\nSupported: PDF, Word (.docx) + text files (txt, md, csv, json, code, …).\n\n🧹 `{p}ask reset` — forget the loaded document.",
        "fa": "📄 **پرسش از یه سند**\n\n۱. روی یه فایل PDF، ورد (.docx) یا متنی با `{p}ask` **ریپلای** بزن تا تحلیلش کنه.\n۲. بعد هر سوالی بپرس: `{p}ask نکات کلیدیش چیه؟`\n\n💡 می‌تونی همون اول هم بپرسی: روی فایل ریپلای بزن و بنویس `{p}ask خلاصه‌ش کن`.\nپشتیبانی: PDF، ورد (.docx) و فایل‌های متنی (txt, md, csv, json, کد و ...).\n\n🧹 `{p}ask reset` — فراموش کردن سند بارگذاری‌شده.",
    },
    "ask_analyzing": {"en": "📄 Analysing **{name}**...", "fa": "📄 در حال تحلیل **{name}**..."},
    "ask_thinking": {"en": "🤔 Thinking...", "fa": "🤔 در حال بررسی..."},
    "ask_loaded": {
        "en": "✅ **{name}** loaded ({chars} chars{trunc}).\n\n{overview}\n\n💬 Ask me anything: `{p}ask <question>`",
        "fa": "✅ **{name}** بارگذاری شد ({chars} کاراکتر{trunc}).\n\n{overview}\n\n💬 هر سوالی داری بپرس: `{p}ask <سوال>`",
    },
    "ask_trunc_note": {"en": ", truncated", "fa": "، برش‌خورده"},
    "ask_no_question": {
        "en": "📄 **{name}** is loaded. Ask a question:\n`{p}ask <your question>`",
        "fa": "📄 **{name}** بارگذاری شده. یه سوال بپرس:\n`{p}ask <سوالت>`",
    },
    "ask_no_doc": {
        "en": "⚠️ No document loaded. Reply to a PDF or text file with `{p}ask` first.",
        "fa": "⚠️ هیچ سندی بارگذاری نشده. اول روی یه فایل PDF یا متنی با `{p}ask` ریپلای بزن.",
    },
    "ask_unsupported": {
        "en": "⚠️ Unsupported file. I can read **PDF** and **text** files (txt, md, csv, json, code, …).",
        "fa": "⚠️ فایل پشتیبانی‌نشده. فقط فایل‌های **PDF** و **متنی** (txt, md, csv, json, کد و ...) رو می‌تونم بخونم.",
    },
    "ask_empty": {
        "en": "⚠️ No readable text found. If this is a scanned PDF (images only), I can't read it — try `{p}ocr` on the pages instead.",
        "fa": "⚠️ متن قابل‌خوندنی پیدا نشد. اگه این PDF اسکن‌شده‌ست (فقط عکس)، نمی‌تونم بخونمش — به‌جاش `{p}ocr` رو روی صفحه‌ها امتحان کن.",
    },
    "ask_pdf_lib": {
        "en": "❌ PDF support is not installed. Run: `pip install pypdf` and restart.",
        "fa": "❌ پشتیبانی PDF نصب نیست. اجرا کن: `pip install pypdf` و ری‌استارت کن.",
    },
    "ask_docx_lib": {
        "en": "❌ Word (.docx) support is not installed. Run: `pip install python-docx` and restart.",
        "fa": "❌ پشتیبانی Word (.docx) نصب نیست. اجرا کن: `pip install python-docx` و ری‌استارت کن.",
    },
    "ask_too_big": {
        "en": "⚠️ File is too large ({size}). Max is {max}.",
        "fa": "⚠️ حجم فایل زیاده ({size}). حداکثر {max}.",
    },
    "ask_dl_error": {"en": "❌ Couldn't download the file: `{e}`", "fa": "❌ دانلود فایل ناموفق بود: `{e}`"},
    "ask_failed": {"en": "❌ Couldn't answer: `{e}`", "fa": "❌ نتونستم جواب بدم: `{e}`"},
    "ask_cleared": {"en": "🧹 Document forgotten.", "fa": "🧹 سند فراموش شد."},

    # .server — VPS resource status
    "server_gathering": {"en": "🖥 Reading server metrics...", "fa": "🖥 در حال خوندن وضعیت سرور..."},
    "server_no_psutil": {
        "en": "❌ Server metrics unavailable. Run: `pip install psutil` and restart.",
        "fa": "❌ نمایش وضعیت سرور در دسترس نیست. اجرا کن: `pip install psutil` و ری‌استارت کن.",
    },
    "server_error": {"en": "❌ Couldn't read server status: `{e}`", "fa": "❌ خواندن وضعیت سرور ناموفق: `{e}`"},

    # .file — text → file
    "file_usage": {
        "en": "📄 **Text → File**\n\n  `{p}file <ext> <text>` — make a file with that extension\n  `{p}file <name.ext> <text>` — use a full filename\n  reply to a message + `{p}file <ext>` — turn it into a file\n\n📝 Examples:\n  `{p}file py print(\"hi\")`\n  `{p}file notes.md # My notes`\n  (reply to a message) `{p}file txt`",
        "fa": "📄 **متن → فایل**\n\n  `{p}file <پسوند> <متن>` — یه فایل با اون پسوند می‌سازه\n  `{p}file <نام.پسوند> <متن>` — با نام کامل دلخواه\n  ریپلای روی یه پیام + `{p}file <پسوند>` — تبدیلش به فایل\n\n📝 مثال‌ها:\n  `{p}file py print(\"سلام\")`\n  `{p}file notes.md # یادداشت من`\n  (ریپلای روی پیام) `{p}file txt`",
    },
    "file_no_text": {
        "en": "⚠️ No text to write. Add text after the extension, or reply to a message with text.",
        "fa": "⚠️ متنی برای نوشتن نیست. بعد از پسوند متن بنویس، یا روی یه پیام دارای متن ریپلای بزن.",
    },
    "file_creating": {"en": "📄 Creating `{name}`...", "fa": "📄 در حال ساخت `{name}`..."},
    "file_caption": {
        "en": "📄 **{name}**  ·  {size}",
        "fa": "📄 **{name}**  ·  {size}",
    },
    "file_failed": {"en": "❌ Couldn't create the file: `{e}`", "fa": "❌ ساخت فایل ناموفق بود: `{e}`"},

    # .fc — FreeCAD Stripe checkout link (usable by members in Allow groups)
    "fc_generating": {"en": "💳 Generating your checkout link...", "fa": "💳 در حال ساخت لینک پرداختت..."},
    "fc_failed": {
        "en": "❌ Couldn't generate a checkout link: `{e}`\nPlease try again in a moment.",
        "fa": "❌ ساخت لینک پرداخت ناموفق بود: `{e}`\nلطفاً چند لحظه دیگه دوباره امتحان کن.",
    },
    "fc_result": {
        "en": (
            "┏━━━━━━━━━━━━━━━━━━━━━┓\n"
            "   💳  **STRIPE CHECKOUT**\n"
            "┗━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            "✅ Your secure payment link is ready!\n\n"
            "🔗  **➤ [ OPEN CHECKOUT PAGE ]({url})**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 _Secured by Stripe_\n"
            "📋 Or tap to copy:\n"
            "`{url}`"
        ),
        # Delivered card is always English (per user request)
        "fa": (
            "┏━━━━━━━━━━━━━━━━━━━━━┓\n"
            "   💳  **STRIPE CHECKOUT**\n"
            "┗━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            "✅ Your secure payment link is ready!\n\n"
            "🔗  **➤ [ OPEN CHECKOUT PAGE ]({url})**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 _Secured by Stripe_\n"
            "📋 Or tap to copy:\n"
            "`{url}`"
        ),
    },

    # .mergetxt — merge all .txt files of a chat
    "mtxt_usage": {
        "en": "📚 **Merge .txt files**\n\n  `{p}mergetxt <channel/group link>` — merge all `.txt` files of that chat into one file\n  `{p}mergetxt` (inside a chat) — merge that chat's `.txt` files\n\nExamples:\n  `{p}mergetxt https://t.me/mychannel`\n  `{p}mergetxt @mychannel`",
        "fa": "📚 **ادغام فایل‌های txt**\n\n  `{p}mergetxt <لینک کانال/گروه>` — همه فایل‌های `.txt` اون چت رو در یک فایل ادغام می‌کنه\n  `{p}mergetxt` (داخل یه چت) — فایل‌های `.txt` همون چت رو ادغام می‌کنه\n\nمثال:\n  `{p}mergetxt https://t.me/mychannel`\n  `{p}mergetxt @mychannel`",
    },
    "mtxt_bad_link": {
        "en": "❌ Couldn't open that chat: `{e}`\nUse a public link/@username, or run `.mergetxt` inside the chat (you must be a member).",
        "fa": "❌ نتونستم اون چت رو باز کنم: `{e}`\nاز لینک عمومی/@یوزرنیم استفاده کن، یا داخل خود چت `.mergetxt` رو بزن (باید عضو باشی).",
    },
    "mtxt_scanning": {"en": "📚 Scanning chat for .txt files...", "fa": "📚 در حال جستجوی فایل‌های txt در چت..."},
    "mtxt_progress": {"en": "📚 Merging... {n} files ({size})", "fa": "📚 در حال ادغام... {n} فایل ({size})"},
    "mtxt_none": {
        "en": "ℹ️ No .txt files found in this chat.",
        "fa": "ℹ️ هیچ فایل .txt توی این چت پیدا نشد.",
    },
    "mtxt_uploading": {"en": "📤 Uploading merged file ({n} files)...", "fa": "📤 در حال آپلود فایل ادغام‌شده ({n} فایل)..."},
    "mtxt_caption": {
        "en": "📚 **{title}**\n━━━━━━━━━━━━━━━━\n📄 Merged **{n}** .txt files  ·  {size}",
        "fa": "📚 **{title}**\n━━━━━━━━━━━━━━━━\n📄 ادغام **{n}** فایل .txt  ·  {size}",
    },
    "mtxt_failed": {"en": "❌ Merge failed: `{e}`", "fa": "❌ ادغام ناموفق بود: `{e}`"},

    # .split — split a large (txt) file into size-limited parts
    "split_usage": {
        "en": "✂️ **Split a file** — Reply to a file with:\n  `{p}split <size>`\n\nExamples:\n  `{p}split 100mb`\n  `{p}split 1gb`\n  `{p}split 250kb`\n\n_Splits at line boundaries (no line is cut). Each part is ≤ the size you choose._",
        "fa": "✂️ **تقسیم فایل** — روی یه فایل ریپلای کن و بزن:\n  `{p}split <حجم>`\n\nمثال:\n  `{p}split 100mb`\n  `{p}split 1gb`\n  `{p}split 250kb`\n\n_برش سر خط کامل انجام می‌شه (هیچ خطی نصفه نمی‌شه). حجم هر تیکه ≤ حجمیه که انتخاب می‌کنی._",
    },
    "split_no_file": {
        "en": "❌ Reply to a file with `{p}split <size>` (e.g. `{p}split 100mb`).",
        "fa": "❌ روی یه فایل ریپلای کن و بزن `{p}split <حجم>` (مثلاً `{p}split 100mb`).",
    },
    "split_bad_size": {
        "en": "❌ Invalid size. Use something like `100mb`, `1gb`, or `250kb` (min 1 KB, max {max}).",
        "fa": "❌ حجم نامعتبره. یه چیزی مثل `100mb`، `1gb` یا `250kb` بنویس (حداقل ۱ کیلوبایت، حداکثر {max}).",
    },
    "split_downloading": {"en": "⬇️ Downloading source file...", "fa": "⬇️ در حال دانلود فایل اصلی..."},
    "split_downloading_pct": {
        "en": "⬇️ Downloading source file... {pct}%  ({done} / {total})",
        "fa": "⬇️ در حال دانلود فایل اصلی... {pct}٪  ({done} / {total})",
    },
    "split_splitting": {
        "en": "✂️ Splitting into ~{size} parts... {n} part(s) so far",
        "fa": "✂️ در حال تقسیم به تیکه‌های ~{size}... تا الان {n} تیکه",
    },
    "split_uploading": {
        "en": "📤 Uploading part {n} ({size})...",
        "fa": "📤 در حال آپلود تیکه {n} ({size})...",
    },
    "split_caption": {
        "en": "✂️ **{name}**\n━━━━━━━━━━━━━━━━\n📦 Part **{n}** of **{total}**  ·  {size}",
        "fa": "✂️ **{name}**\n━━━━━━━━━━━━━━━━\n📦 تیکه **{n}** از **{total}**  ·  {size}",
    },
    "split_done": {
        "en": "✅ Done! Split into **{n}** parts (total {size}).",
        "fa": "✅ تموم شد! به **{n}** تیکه تقسیم شد (مجموع {size}).",
    },
    "split_failed": {"en": "❌ Split failed: `{e}`", "fa": "❌ تقسیم ناموفق بود: `{e}`"},

    # .style / .aged / .cartoon
    "style_usage": {
        "en": "🎨 **Style transfer** — Reply to a photo with:\n  `{p}style <style>`\n\nPresets: `vangogh`, `monet`, `anime`, `ghibli`, `pixar`, `disney`, `watercolor`, `oil`, `sketch`, `cyberpunk`, `comic`, `popart`, `lego`, `minecraft`, `pixel`, `vaporwave`, `ukiyoe`, `noir`, `claymation`\n\nPersian: `انیمه`, `گیبلی`, `پیکسار`, `ون‌گوگ`, `آبرنگ`, `رنگ‌روغن`, `سایبرپانک`, `کمیک`, `لگو`, `نوآر` ...\nOr any free-form description (e.g. `{p}style steampunk illustration with brass gears`).",
        "fa": "🎨 **تغییر سبک هنری** — روی یه عکس ریپلای بزن:\n  `{p}style <سبک>`\n\nسبک‌های آماده: `vangogh`, `monet`, `anime`, `ghibli`, `pixar`, `disney`, `watercolor`, `oil`, `sketch`, `cyberpunk`, `comic`, `popart`, `lego`, `minecraft`, `pixel`, `vaporwave`, `ukiyoe`, `noir`, `claymation`\n\nفارسی: `انیمه`, `گیبلی`, `پیکسار`, `ون‌گوگ`, `آبرنگ`, `رنگ‌روغن`, `سایبرپانک`, `کمیک`, `لگو`, `نوآر` ...\nیا هر توصیف آزاد (مثلاً `{p}style steampunk illustration with brass gears`).",
    },
    "style_processing": {"en": "🎨 Restyling → {s}...", "fa": "🎨 تغییر سبک → {s}..."},
    "style_caption":    {"en": "🎨 Style: **{s}**",    "fa": "🎨 سبک: **{s}**"},

    "aged_usage": {
        "en": "👴 **Age / De-age** — Reply to a photo of a person with:\n  `{p}aged +20` — make 20 years older\n  `{p}aged -10` — make 10 years younger\n\nRange: 1 to 80 years. Persian digits OK (`{p}aged ۱۵`).",
        "fa": "👴 **پیر / جوون کن** — روی یه عکس ریپلای بزن:\n  `{p}aged +20` — ۲۰ سال پیرتر کن\n  `{p}aged -10` — ۱۰ سال جوون‌تر کن\n\nبازه: ۱ تا ۸۰ سال. اعداد فارسی هم قبوله (`{p}aged ۱۵`).",
    },
    "aged_processing": {"en": "👴 Aging photo ({y} years)...", "fa": "👴 در حال تغییر سن ({y} سال)..."},
    "aged_caption":    {"en": "👴 Aged: **{y} years**",        "fa": "👴 تغییر سن: **{y} سال**"},

    "cartoon_processing": {"en": "🧒 Cartoonifying ({s})...", "fa": "🧒 در حال کارتونی کردن ({s})..."},
    "cartoon_caption":    {"en": "🧒 Cartoon: **{s}**",       "fa": "🧒 کارتونی: **{s}**"},

    # Group / chat summariser (.sum)
    "sum_usage": {
        "en": "📊 **Chat summariser**\n\n  `{p}sum` — summarise last 50 messages\n  `{p}sum <N>` — summarise last N messages (max 200)\n\nWorks in private chats and groups. Output is always in Persian.",
        "fa": "📊 **خلاصه‌ساز چت**\n\n  `{p}sum` — خلاصه‌ی ۵۰ پیام آخر\n  `{p}sum <N>` — خلاصه‌ی N پیام آخر (حداکثر ۲۰۰)\n\nهم در پی‌وی هم در گروه‌ها کار می‌کنه. خروجی همیشه فارسی.",
    },
    "sum_reading":   {"en": "📊 Reading last {n} messages...", "fa": "📊 در حال خوندن {n} پیام اخیر..."},
    "sum_no_msgs":   {"en": "ℹ️ Nothing meaningful to summarise.", "fa": "ℹ️ پیامی برای خلاصه‌سازی پیدا نشد."},
    "sum_failed":    {"en": "❌ Summarisation failed: {e}", "fa": "❌ خلاصه‌سازی ناموفق بود: {e}"},
    "sum_header":    {"en": "📊 **Summary of last {n} messages**\n\n{s}", "fa": "📊 **خلاصه‌ی {n} پیام اخیر**\n\n{s}"},

    # TL;DR — link summariser
    "tldr_usage": {
        "en": "📰 **TL;DR — link summariser**\n\n  `{p}tldr <url>` — summarise a URL\n  reply + `{p}tldr` — auto-detect URLs in the replied message\n\nWorks with: news articles, blog posts, GitHub repos, YouTube, and generic web pages.\nUp to **3 links** per call.",
        "fa": "📰 **TL;DR — خلاصه‌ساز لینک**\n\n  `{p}tldr <لینک>` — خلاصه‌ی یه لینک\n  ریپلای + `{p}tldr` — تشخیص خودکار لینک‌ها در پیام ریپلای‌شده\n\nپشتیبانی: خبر، مقاله، ریپوی GitHub، یوتیوب، هر صفحه‌ی وب.\nحداکثر **۳ لینک** در هر دستور.",
    },
    "tldr_no_url": {
        "en": "⚠️ No URL found. Send a URL after the command or reply to a message containing a link.",
        "fa": "⚠️ هیچ لینکی پیدا نشد. بعد از دستور لینک بفرست، یا روی پیامی که لینک داره ریپلای بزن.",
    },
    "tldr_processing_one": {
        "en": "📰 Reading & summarising...\n_{u}_",
        "fa": "📰 در حال خوندن و خلاصه‌سازی...\n_{u}_",
    },
    "tldr_processing_multi": {
        "en": "📰 Reading & summarising {n} links...",
        "fa": "📰 در حال خوندن و خلاصه‌سازی {n} لینک...",
    },
    "tldr_done_one": {"en": "📰 **TL;DR** of {u}", "fa": "📰 **خلاصه‌ی** {u}"},
    "tldr_separator": {"en": "\n\n━━━━━━━━━━━━━━━━━━━━\n\n", "fa": "\n\n━━━━━━━━━━━━━━━━━━━━\n\n"},

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

    # Text-to-Speech (.say / .voice)
    "say_usage": {
        "en": "🔊 **Text-to-Speech**\n\n  `{p}say <text>` — send text as a voice message\n  reply + `{p}say` — speak the replied message\n  `{p}say -v onyx <text>` — override voice for this message\n\n🎙 Current voice: `{v}` · model: `{m}`\n🌍 Supports Persian, English, Arabic & 50+ languages (auto-detected).\n\n🎛 Change default voice: `{p}voice <name>`",
        "fa": "🔊 **تبدیل متن به گفتار**\n\n  `{p}say <متن>` — متن رو به صورت ویس می‌فرسته\n  ریپلای + `{p}say` — پیام ریپلای‌شده رو می‌خونه\n  `{p}say -v onyx <متن>` — انتخاب صدا فقط برای همین ویس\n\n🎙 صدای فعلی: `{v}` · مدل: `{m}`\n🌍 فارسی، انگلیسی، عربی و بیش از ۵۰ زبان (تشخیص خودکار).\n\n🎛 تغییر صدای پیش‌فرض: `{p}voice <نام>`",
    },
    "say_not_ready": {
        "en": "❌ **Voice unavailable:** {err}\n\n🔧 Set `EMERGENT_LLM_KEY=...` in `.env` and restart, or reinstall:\n`pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`",
        "fa": "❌ **قابلیت صدا در دسترس نیست:** {err}\n\n🔧 در `.env` مقدار `EMERGENT_LLM_KEY=...` رو ست کن و ری‌استارت کن، یا نصب مجدد:\n`pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`",
    },
    "say_processing": {"en": "🔊 Generating voice ({v})...", "fa": "🔊 در حال ساخت ویس ({v})..."},
    "say_reply_error": {"en": "❌ Error fetching replied message: {e}", "fa": "❌ خطا در دریافت پیام ریپلای: {e}"},
    "say_send_failed": {"en": "❌ Failed to send voice: {e}", "fa": "❌ ارسال ویس ناموفق: {e}"},
    "voice_show": {
        "en": "🎙 **Voice settings**\n\n🔊 Voice: `{v}`\n📚 Model: `{m}`\n\n🌟 Available voices:\n  `alloy` neutral · `ash` clear · `coral` warm\n  `echo` calm · `fable` expressive · `nova` energetic\n  `onyx` deep · `sage` measured · `shimmer` bright\n\n🛠 Change:\n  `{p}voice nova`\n  `{p}voice model tts-1-hd` (HD) / `tts-1` (fast)",
        "fa": "🎙 **تنظیمات صدا**\n\n🔊 صدا: `{v}`\n📚 مدل: `{m}`\n\n🌟 صداهای موجود:\n  `alloy` خنثی · `ash` شفاف · `coral` گرم\n  `echo` آروم · `fable` بیانگر · `nova` پرانرژی\n  `onyx` بم · `sage` متین · `shimmer` روشن\n\n🛠 تغییر:\n  `{p}voice nova`\n  `{p}voice model tts-1-hd` (کیفیت بالا) / `tts-1` (سریع)",
    },
    "voice_set": {"en": "✅ Default voice set to `{v}`.", "fa": "✅ صدای پیش‌فرض روی `{v}` تنظیم شد."},
    "voice_invalid": {
        "en": "⚠️ Unknown voice. Choose one of: `alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.\nSee `{p}voice` for details.",
        "fa": "⚠️ صدای نامعتبر. یکی از این‌ها رو انتخاب کن: `alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.\nجزئیات: `{p}voice`",
    },
    "voice_model_set": {"en": "✅ TTS model set to `{m}`.", "fa": "✅ مدل صدا روی `{m}` تنظیم شد."},
    "voice_model_invalid": {
        "en": "⚠️ Model must be `tts-1` (fast) or `tts-1-hd` (HD).\nExample: `{p}voice model tts-1-hd`",
        "fa": "⚠️ مدل باید `tts-1` (سریع) یا `tts-1-hd` (کیفیت بالا) باشه.\nمثال: `{p}voice model tts-1-hd`",
    },

    # URL Uploader (.up)
    "up_usage": {
        "en": "📥 **URL Uploader**\n\n  `{p}up <link>` — download a file from a direct link and upload it here\n  reply + `{p}up` — auto-detect the link in the replied message\n\nℹ️ Images / videos / audio are sent as media, everything else as a file.\n💾 Max size: 2 GB.",
        "fa": "📥 **آپلودر لینک**\n\n  `{p}up <لینک>` — فایل رو از یه لینک مستقیم دانلود و همین‌جا آپلود می‌کنه\n  ریپلای + `{p}up` — تشخیص خودکار لینک از پیام ریپلای‌شده\n\nℹ️ عکس/ویدیو/صوت به‌صورت مدیا، بقیه به‌صورت فایل ارسال می‌شن.\n💾 حداکثر حجم: ۲ گیگابایت.",
    },
    "up_no_url": {
        "en": "⚠️ No direct link found. Send a URL after the command or reply to a message containing a link.",
        "fa": "⚠️ لینک مستقیمی پیدا نشد. بعد از دستور لینک بفرست، یا روی پیامی که لینک داره ریپلای بزن.",
    },
    "up_starting": {"en": "📥 Fetching...\n_{u}_", "fa": "📥 در حال دریافت...\n_{u}_"},
    "up_downloading": {"en": "📥 Downloading... `{done}`", "fa": "📥 در حال دانلود... `{done}`"},
    "up_downloading_pct": {
        "en": "📥 Downloading...\n`{bar}` {pct}%\n`{done}` / `{total}`",
        "fa": "📥 در حال دانلود...\n`{bar}` {pct}%\n`{done}` / `{total}`",
    },
    "up_uploading": {"en": "📤 Uploading: _{name}_ ...", "fa": "📤 در حال آپلود: _{name}_ ..."},
    "up_uploading_pct": {
        "en": "📤 Uploading...\n`{bar}` {pct}%\n`{done}` / `{total}`",
        "fa": "📤 در حال آپلود...\n`{bar}` {pct}%\n`{done}` / `{total}`",
    },
    "up_too_big": {
        "en": "⚠️ File is too large (`{size}`). Max allowed is `{max}`.",
        "fa": "⚠️ حجم فایل زیاده (`{size}`). حداکثر مجاز `{max}` است.",
    },
    "up_failed": {"en": "❌ Upload failed: `{e}`", "fa": "❌ آپلود ناموفق بود: `{e}`"},
    "up_caption": {
        "en": "{icon} **File Uploaded**\n━━━━━━━━━━━━━━━━\n📄 **Name:** `{name}`\n🏷 **Type:** `{type}`\n💾 **Size:** `{size}`\n🌐 **Source:** `{src}`",
        "fa": "{icon} **فایل آپلود شد**\n━━━━━━━━━━━━━━━━\n📄 **نام:** `{name}`\n🏷 **نوع:** `{type}`\n💾 **حجم:** `{size}`\n🌐 **منبع:** `{src}`",
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
            "  `{p}r [hint]` — **manually generate** AI reply for current chat\n"
            "     • reply to a message to focus on it\n"
            "     • reply to an **image** → AI analyses the picture & answers your question about it\n"
            "     • example: reply to a photo with `{p}r چه برندی؟` / `{p}r what's wrong here?`\n\n"
            "🌐 **Translation**\n"
            "  `{p}lang <code>` — set default target language\n"
            "  `{p}tl <text>` — auto fa↔en (Persian→English, else→Persian)\n"
            "  `{p}tl <lang> <text>` — explicit target (e.g. `{p}tl arabic hello`)\n"
            "  reply + `{p}tl [lang]` — translate replied message\n"
            "  reply + `{p}tl` — translate replied message\n"
            "  `{p}to <code> <text>` — edit message to that language\n"
            "     example: `{p}to en سلام چطوری`\n\n"
            "🎨 **Image**\n"
            "  `{p}img <description>` — generate image (Nano Banana)\n"
            "     supports `--ar 16:9` / `--landscape` / `--portrait` flags\n"
            "  `{p}imgedit <change>` — edit image (reply to image)\n"
            "  `{p}mix [prompt] — combine two images (reply to one + attach another, or reply to an album)`\n"
            "  `{p}style <style>` — re-render image in an artistic style (reply)\n"
            "     presets: vangogh, anime, ghibli, pixar, cyberpunk, watercolor, lego, ...\n"
            "     or any free-form description\n"
            "  `{p}aged +20` / `{p}aged -10` — age or de-age person in photo (reply)\n"
            "  `{p}cartoon [pixar|disney|anime|ghibli]` — cartoonify a photo (reply)\n"
            "  `{p}ocr` — extract text from image (reply to image)\n"
            "  `{p}imgmodel <model>` — change image model\n"
            "  `{p}imgsize [ratio]` — view/set default aspect ratio\n\n"
            "📰 **Web**\n"
            "  `{p}tldr <url>` — summarise a link (always in Persian)\n"
            "  reply + `{p}tldr` — auto-detect URLs in replied message\n"
            "  `{p}up <link>` — download a file from a link & upload it here\n"
            "     reply + `{p}up` — auto-detect the link in the replied message\n"
            "  `{p}ask <question>` — analyse a PDF/text file & answer questions\n"
            "     reply to a file + `{p}ask`, then ask follow-ups anytime\n"
            "  `{p}file <ext> <text>` — make a file from text (or reply to a message)\n"
            "  `{p}mergetxt <link>` — merge all .txt files of a channel/group into one file\n"
            "  `{p}split <size>` — reply to a file to split it into parts (e.g. `{p}split 100mb`)\n\n"
            "🔊 **Voice (Text-to-Speech)**\n"
            "  `{p}say <text>` — send text as a natural voice message\n"
            "     reply + `{p}say` — speak the replied message\n"
            "     `{p}say -v onyx <text>` — override voice for this message\n"
            "  `{p}voice [name]` — view/set default voice (9 voices)\n"
            "  `{p}voice model tts-1|tts-1-hd` — set quality\n\n"
            "📊 **Chat**\n"
            "  `{p}sum [N]` — summarise last N messages (default 50, max 200)\n\n"
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
            "  `{p}server` — VPS resource usage (CPU / RAM / disk)\n"
            "  `{p}fc` — get a Stripe checkout link (works for members in Allow groups)\n"
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
            "  `{p}r [hint]` — **تولید پاسخ دستی** با AI بر اساس چت فعلی\n"
            "     • روی یه پیام ریپلای بزن تا روی همون تمرکز کنه\n"
            "     • روی یه **عکس** ریپلای بزن → AI عکس رو تحلیل می‌کنه و به سؤالت جواب می‌ده\n"
            "     • مثال: روی عکس ریپلای + `{p}r چه برندی؟` یا `{p}r این چیه؟`\n\n"
            "🌐 **ترجمه**\n"
            "  `{p}lang <code>` — تنظیم زبان پیش‌فرض (fa, en, ar, ...)\n"
            "  `{p}tl <متن>` — تشخیص خودکار فارسی↔انگلیسی\n"
            "  `{p}tl <زبون> <متن>` — مقصد دستی (مثلاً `{p}tl عربی سلام`)\n"
            "  ریپلای + `{p}tl [زبون]` — ترجمه پیام ریپلای‌شده\n"
            "  ریپلای + `{p}tl` — ترجمه پیام ریپلای شده\n"
            "  `{p}to <code> <متن>` — متن رو ادیت می‌کنه به زبان دیگه\n"
            "     مثال: `{p}to en سلام چطوری`\n\n"
            "🎨 **تصویر**\n"
            "  `{p}img <توضیح>` — تولید تصویر با Nano Banana\n"
            "     قابل ترکیب با `--ar 16:9` / `--افقی` / `--استوری`\n"
            "  `{p}imgedit <توضیح>` — ویرایش عکس (روی عکس reply بزن)\n"
            "  `{p}mix [پرامپت]` — ترکیب دو عکس (روی یکی reply بزن + دومی رو الصاق کن، یا روی آلبوم reply بزن)\n"
            "  `{p}style <سبک>` — تغییر سبک هنری عکس (روی عکس reply بزن)\n"
            "     سبک‌های آماده: انیمه، گیبلی، پیکسار، ون‌گوگ، آبرنگ، سایبرپانک، لگو، ...\n"
            "     یا هر توصیف آزاد دلخواه\n"
            "  `{p}aged +20` / `{p}aged -10` — پیر/جوون کردن شخص توی عکس (روی عکس reply)\n"
            "  `{p}cartoon [pixar|disney|anime|ghibli]` — کارتونی کردن عکس (روی عکس reply)\n"
            "  `{p}ocr` — استخراج متن از عکس (روی عکس reply بزن)\n"
            "  `{p}imgmodel <model>` — تغییر مدل تصویر\n"
            "  `{p}imgsize [ابعاد]` — نمایش/تنظیم ابعاد پیش‌فرض\n\n"
            "📰 **وب**\n"
            "  `{p}tldr <لینک>` — خلاصه‌سازی لینک (همیشه فارسی)\n"
            "  ریپلای + `{p}tldr` — تشخیص خودکار لینک‌ها در پیام ریپلای‌شده\n"
            "  `{p}up <لینک>` — دانلود فایل از یه لینک و آپلودش همین‌جا\n"
            "     ریپلای + `{p}up` — تشخیص خودکار لینک از پیام ریپلای‌شده\n"
            "  `{p}ask <سوال>` — تحلیل فایل PDF/متنی و پاسخ به سوالات\n"
            "     روی فایل ریپلای بزن + `{p}ask`، بعد هر وقت خواستی سوال بپرس\n"
            "  `{p}file <پسوند> <متن>` — ساخت فایل از متن (یا ریپلای روی یه پیام)\n"
            "  `{p}mergetxt <لینک>` — ادغام همه فایل‌های .txt یه کانال/گروه در یک فایل\n"
            "  `{p}split <حجم>` — روی یه فایل ریپلای کن تا به تیکه تقسیم بشه (مثلاً `{p}split 100mb`)\n\n"
            "🔊 **صدا (متن به گفتار)**\n"
            "  `{p}say <متن>` — متن رو به صورت ویس طبیعی می‌فرسته\n"
            "     ریپلای + `{p}say` — پیام ریپلای‌شده رو می‌خونه\n"
            "     `{p}say -v onyx <متن>` — انتخاب صدا فقط برای همین ویس\n"
            "  `{p}voice [نام]` — نمایش/تنظیم صدای پیش‌فرض (۹ صدا)\n"
            "  `{p}voice model tts-1|tts-1-hd` — تنظیم کیفیت\n\n"
            "📊 **چت**\n"
            "  `{p}sum [N]` — خلاصه‌سازی N پیام آخر (پیش‌فرض ۵۰، حداکثر ۲۰۰)\n\n"
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
            "  `{p}server` — مصرف منابع سرور (پردازنده/رم/دیسک)\n"
            "  `{p}fc` — گرفتن لینک پرداخت استرایپ (برای اعضای گروه‌های Allow هم کار می‌کنه)\n"
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
# ────────── TL;DR — Web Page / Article / Repo Summariser ──────────
_URL_RE = re.compile(r"https?://[^\s<>'\"`{}|^]+", re.IGNORECASE)


def _extract_urls(text: str, max_urls: int = 3) -> list[str]:
    """Extract up to `max_urls` distinct URLs from `text`, trailing punct stripped."""
    if not text:
        return []
    seen: list[str] = []
    for raw in _URL_RE.findall(text):
        # Strip plain trailing punctuation
        url = raw.rstrip(".,;:!?>'\"")
        # Balance ( and ) — keep trailing ')' only if there's a matching '('.
        # Handles Wikipedia URLs like /Python_(programming_language).
        while url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        # Strip any remaining standalone trailing brackets that aren't part of a path
        url = url.rstrip("]}")
        if url and url not in seen:
            seen.append(url)
            if len(seen) >= max_urls:
                break
    return seen


def _classify_url(url: str) -> str:
    u = url.lower()
    if re.search(r"//(?:www\.)?github\.com/[^/]+/[^/?#]+", u):
        return "github"
    if "youtube.com/watch" in u or "youtu.be/" in u or "music.youtube.com/watch" in u:
        return "youtube"
    return "generic"


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>",
                              re.DOTALL | re.IGNORECASE)


def _strip_html(s: str) -> str:
    """Quick-and-dirty HTML → plain text. Good enough for summarisation."""
    if not s:
        return ""
    s = _HTML_SCRIPT_RE.sub(" ", s)
    s = _HTML_TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _fetch_page_text(url: str, max_chars: int = 6000) -> dict:
    """Download a URL and return {title, description, body, url}.
    Blocking — must be called via `asyncio.to_thread`.
    Raises on network failure.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        ctype = resp.headers.get("Content-Type", "").lower()
        final_url = resp.url or url
        if "html" not in ctype and "text/plain" not in ctype:
            raise ValueError(f"unsupported content type: {ctype or '?'}")
        raw = resp.read(800_000).decode("utf-8", errors="ignore")

    # Title + OpenGraph description
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.I)
    title = html.unescape(title_m.group(1).strip()) if title_m else ""

    desc_m = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\']'
        r'[^>]+content=["\']([^"\']+)["\']', raw, re.IGNORECASE)
    desc = html.unescape(desc_m.group(1).strip()) if desc_m else ""

    # Main content: try <article> / <main>, else collect <p> tags, else strip body
    body = ""
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", raw, re.DOTALL | re.I)
        if m:
            candidate = _strip_html(m.group(1))
            if len(candidate) > 200:
                body = candidate
                break

    if not body:
        paras = re.findall(r"<(?:p|h[1-3]|li)\b[^>]*>(.*?)</(?:p|h[1-3]|li)>",
                            raw, re.DOTALL | re.I)
        if paras:
            body = " ".join(_strip_html(p) for p in paras[:40])
        else:
            body = _strip_html(raw)

    body = re.sub(r"\s+", " ", body).strip()
    return {
        "url": final_url,
        "title": title[:300],
        "description": desc[:500],
        "body": body[:max_chars],
    }


def _parse_github_repo(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL. Strips a `.git` suffix safely."""
    m = re.search(r"//(?:www\.)?github\.com/([^/]+)/([^/?#]+)", url, re.I)
    if not m:
        return None
    return m.group(1), re.sub(r"\.git$", "", m.group(2))


def _fetch_github_repo(url: str) -> dict | None:
    """Fetch GitHub repo metadata + README via the public API (no auth needed)."""
    parsed = _parse_github_repo(url)
    if not parsed:
        return None
    owner, repo = parsed
    try:
        meta = _http_json(f"https://api.github.com/repos/{owner}/{repo}", timeout=20)
    except Exception as e:  # noqa: BLE001
        log.warning(f"[tldr] github API failed: {e}")
        return None
    readme_text = ""
    try:
        # README is base64-encoded in the response
        rd = _http_json(f"https://api.github.com/repos/{owner}/{repo}/readme", timeout=20)
        if rd.get("content"):
            readme_text = base64.b64decode(rd["content"]).decode("utf-8", errors="ignore")
            readme_text = _strip_html(readme_text)[:5000]
    except Exception as e:  # noqa: BLE001
        log.debug(f"[tldr] github readme fetch: {e}")
    return {
        "full_name": meta.get("full_name"),
        "description": meta.get("description") or "",
        "language": meta.get("language") or "",
        "stars": meta.get("stargazers_count") or 0,
        "forks": meta.get("forks_count") or 0,
        "open_issues": meta.get("open_issues_count") or 0,
        "homepage": meta.get("homepage") or "",
        "topics": meta.get("topics") or [],
        "license": (meta.get("license") or {}).get("spdx_id") or "",
        "readme": readme_text,
    }


async def _ai_summarise(prompt: str) -> str | None:
    """One-shot summarisation call. Reuses configured chat model & key."""
    ready, _ = _ai_ready()
    if not ready or not prompt.strip():
        return None
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"tldr-{time.time_ns()}",
            system_message=(
                "You are an expert summariser. You write tight, factual, well-structured "
                "summaries with no preamble, no apologies, no meta-commentary. "
                "Use Markdown formatting and bullet points where helpful."
            ),
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        resp = await chat.send_message(UserMessage(text=prompt))
        return str(resp).strip()
    except Exception as e:  # noqa: BLE001
        log.error(f"[tldr] AI summarise error: {e}")
        return None


# ────────── Document Q&A (.ask) helpers ──────────
MAX_DOC_BYTES = 25 * 1024 * 1024   # 25 MB download cap
MAX_DOC_CHARS = 100_000            # ~25k tokens of context
_DOC_TEXT_EXTS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "xml", "yaml", "yml", "log",
    "py", "js", "ts", "jsx", "tsx", "java", "c", "cpp", "h", "hpp", "go", "rs",
    "rb", "php", "sh", "bash", "html", "htm", "css", "scss", "sql", "ini", "conf",
    "cfg", "toml", "env", "srt", "vtt", "tex",
}
# In-memory per-chat document cache: chat_id -> {name, text, history, truncated, ts}
_doc_cache: dict[int, dict] = {}


def _doc_is_supported(name: str, mime: str) -> bool:
    ext = os.path.splitext(name or "")[1].lower().lstrip(".")
    mime = (mime or "").lower()
    if ext == "pdf" or mime == "application/pdf":
        return True
    if ext == "docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return True
    if mime.startswith("text/"):
        return True
    if ext in _DOC_TEXT_EXTS:
        return True
    if mime in ("application/json", "application/xml", "application/csv",
                "application/x-yaml", "application/x-sh", "application/javascript"):
        return True
    return False


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraphs + table cells from a .docx file."""
    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_document_text(data: bytes, name: str, mime: str) -> tuple[str | None, str | None, bool]:
    """Return (text, error_key, truncated). error_key is one of
    'pdf_lib' / 'docx_lib' / 'unsupported' / 'empty' / raw-string, or None on success."""
    ext = os.path.splitext(name or "")[1].lower().lstrip(".")
    mime = (mime or "").lower()
    is_docx = (ext == "docx" or
               mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    try:
        if ext == "pdf" or mime == "application/pdf":
            if not PDF_LIB_OK:
                return None, "pdf_lib", False
            reader = pypdf.PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001
                    continue
            text = "\n".join(parts)
        elif is_docx:
            if not DOCX_LIB_OK:
                return None, "docx_lib", False
            text = _extract_docx_text(data)
        elif _doc_is_supported(name, mime):
            text = data.decode("utf-8", errors="replace")
        else:
            return None, "unsupported", False
    except Exception as e:  # noqa: BLE001
        log.error(f"[.ask] extract error: {e}")
        return None, str(e)[:200], False
    text = (text or "").strip()
    if not text:
        return None, "empty", False
    truncated = len(text) > MAX_DOC_CHARS
    return text[:MAX_DOC_CHARS], None, truncated


async def _answer_document(doc: dict, question: str) -> tuple[str | None, str | None]:
    """Answer `question` about the cached `doc`, using recent Q&A history for
    follow-up context. Returns (answer, error)."""
    ready, ai_err = _ai_ready()
    if not ready:
        return None, ai_err or "AI not configured"
    history = doc.get("history", [])
    hist_block = ""
    if history:
        hist_block = "\n\nEarlier in this conversation:\n" + "\n".join(
            f"Q: {q}\nA: {a}" for q, a in history[-4:]) + "\n"
    user_text = (
        f"=== DOCUMENT: {doc['name']} ===\n{doc['text']}\n=== END DOCUMENT ==="
        f"{hist_block}\n\nQuestion: {question}"
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"askdoc-{time.time_ns()}",
            system_message=(
                "You answer questions about a document provided by the user. Base your "
                "answers ONLY on the document's content; if the answer is not in the "
                "document, clearly say it is not covered. Be accurate and concise. "
                "Reply in the SAME language as the user's question. Use Markdown "
                "(bold key terms, bullet points) where helpful."
            ),
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        resp = await chat.send_message(UserMessage(text=user_text))
        return str(resp).strip(), None
    except Exception as e:  # noqa: BLE001
        log.error(f"[.ask] answer error: {e}")
        return None, str(e)


async def _reply_long(status, chat_id, text: str, reply_to) -> None:
    """Edit `status` with `text`, spilling overflow into follow-up messages
    (Telegram ~4096-char limit)."""
    if len(text) <= 3900:
        try:
            await status.edit(text, link_preview=False)
        except Exception:  # noqa: BLE001
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
            await client.send_message(chat_id, text, link_preview=False, reply_to=reply_to)
        return
    await status.edit(text[:3900] + "\n\n…", link_preview=False)
    rest = text[3900:]
    while rest:
        piece, rest = rest[:3900], rest[3900:]
        await client.send_message(chat_id, piece, link_preview=False, reply_to=reply_to)


# ────────── Server status (.server) helpers ──────────
def _fmt_uptime(seconds) -> str:
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m or not parts:
        parts.append(f"{m}m")
    return " ".join(parts)


async def _gather_server_status() -> dict:
    cpu = await asyncio.to_thread(psutil.cpu_percent, 0.5)
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load = psutil.getloadavg()
    except (AttributeError, OSError):
        load = (0.0, 0.0, 0.0)
    net = psutil.net_io_counters()
    cpu_temp = None
    try:
        for _name, entries in (psutil.sensors_temperatures() or {}).items():
            for e in entries:
                if e.current:
                    cpu_temp = e.current
                    break
            if cpu_temp:
                break
    except Exception:  # noqa: BLE001
        cpu_temp = None
    return {
        "cpu": cpu,
        "cores": psutil.cpu_count(logical=True) or 0,
        "ram_pct": vm.percent, "ram_used": vm.used, "ram_total": vm.total,
        "disk_pct": du.percent, "disk_used": du.used, "disk_total": du.total,
        "load": load, "net_sent": net.bytes_sent, "net_recv": net.bytes_recv,
        "sys_uptime": time.time() - psutil.boot_time(),
        "bot_uptime": time.time() - stats["start_time"],
        "os": f"{platform.system()} {platform.release()}",
        "host": platform.node(), "py": platform.python_version(),
        "cpu_temp": cpu_temp,
    }


def _ascii_bar(pct, width=16) -> str:
    """Fixed-width block-character bar for the monospace ASCII server card."""
    pct = max(0, min(100, int(round(pct))))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _format_server_status(d: dict, lang: str) -> str:
    """Render a fixed-width ASCII card (inside a monospace code block) so the
    bars and columns stay perfectly aligned across Telegram clients."""
    W = 42  # inner width
    lo = d["load"]

    def row(s: str) -> str:
        s = s[:W - 2]
        return "│ " + s.ljust(W - 2) + " │"

    def sep(left="├", right="┤") -> str:
        return left + "─" * W + right

    temp = f"  {d['cpu_temp']:.0f}C" if d.get("cpu_temp") else ""
    lines = [
        "┌" + "─" * W + "┐",
        "│" + "SERVER  STATUS".center(W) + "│",
        sep(),
        row(f"CPU   {_ascii_bar(d['cpu'])} {int(round(d['cpu'])):>3}%"),
        row(f"RAM   {_ascii_bar(d['ram_pct'])} {int(round(d['ram_pct'])):>3}%"),
        row(f"DISK  {_ascii_bar(d['disk_pct'])} {int(round(d['disk_pct'])):>3}%"),
        sep(),
        row(f"RAM    {_human_size(d['ram_used'])} / {_human_size(d['ram_total'])}"),
        row(f"Disk   {_human_size(d['disk_used'])} / {_human_size(d['disk_total'])}"),
        row(f"CPU    {d['cores']} cores{temp}"),
        row(f"Load   {lo[0]:.2f}  {lo[1]:.2f}  {lo[2]:.2f}"),
        row(f"Net    up {_human_size(d['net_sent'])}  dn {_human_size(d['net_recv'])}"),
        sep(),
        row(f"Server up  {_fmt_uptime(d['sys_uptime'])}"),
        row(f"Bot up     {_fmt_uptime(d['bot_uptime'])}"),
        row(f"OS         {d['os']}"),
        row(f"Python     {d['py']}"),
        row(f"Host       {d['host']}"),
        "└" + "─" * W + "┘",
    ]
    box = "\n".join(lines)
    header = "🖥 **وضعیت لحظه‌ای سرور**" if lang == "fa" else "🖥 **Live Server Status**"
    return f"{header}\n```\n{box}\n```"


def _tldr_prompt(content: dict, lang: str) -> str:
    """Build the summarisation prompt for a fetched URL payload."""
    lang_name = "Persian (Farsi)" if lang == "fa" else "English"
    return (
        f"Summarise the following web page in {lang_name}.\n"
        f"Format:\n"
        f"• Start with **one short headline** line (no labels).\n"
        f"• Then 4-6 bullet points covering the main topic, key facts/findings, "
        f"and why it matters.\n"
        f"• Bold key terms with **double asterisks**.\n"
        f"• No preamble, no 'Here is the summary', no closing remarks.\n"
        f"• If the page is mostly an error / paywall / login wall, say so and stop.\n\n"
        f"URL: {content['url']}\n"
        f"TITLE: {content.get('title','')}\n"
        f"DESCRIPTION: {content.get('description','')}\n\n"
        f"BODY:\n{content.get('body','')[:6000]}"
    )


def _tldr_github_prompt(info: dict, url: str, lang: str) -> str:
    lang_name = "Persian (Farsi)" if lang == "fa" else "English"
    return (
        f"Summarise this GitHub repository in {lang_name}.\n"
        f"Format:\n"
        f"• First line: one-sentence project pitch.\n"
        f"• Then 3-5 bullets: what it does, who it's for, notable features, how to run it.\n"
        f"• Bold key terms.\n"
        f"• No preamble or sign-off.\n\n"
        f"REPO: {info['full_name']}  ({url})\n"
        f"DESCRIPTION: {info['description']}\n"
        f"LANGUAGE: {info['language']} · STARS: {info['stars']:,} · "
        f"FORKS: {info['forks']:,} · ISSUES: {info['open_issues']:,}\n"
        f"TOPICS: {', '.join(info['topics']) or '—'}\n"
        f"LICENSE: {info['license'] or '—'}\n\n"
        f"README (first 5k chars):\n{info['readme']}"
    )


async def _tldr_one(url: str, lang: str) -> str:
    """Fetch + summarise one URL. Returns the formatted reply chunk."""
    kind = _classify_url(url)
    short_url = url if len(url) <= 90 else url[:87] + "…"

    if kind == "github":
        info = await asyncio.to_thread(_fetch_github_repo, url)
        if not info:
            return f"❌ GitHub: `{short_url}` — couldn't fetch repo info"
        ai = await _ai_summarise(_tldr_github_prompt(info, url, lang))
        header = (
            f"📦 [{info['full_name']}]({url})\n"
            f"⭐ {info['stars']:,} · 🍴 {info['forks']:,} · "
            f"🐛 {info['open_issues']:,} · {info['language'] or '—'}"
        )
        return header + ("\n\n" + ai if ai else f"\n\n_{info['description']}_")

    if kind == "youtube":
        # Extract video ID and title via existing oEmbed helper
        title_q = await asyncio.to_thread(_youtube_title_query, url) or "YouTube video"
        body = f"YouTube video. Title and artist: {title_q}."
        ai = await _ai_summarise(_tldr_prompt(
            {"url": url, "title": title_q, "description": "", "body": body}, lang))
        return f"▶️ [{title_q}]({url})\n\n" + (ai or "_(no AI summary available)_")

    # Generic web page
    try:
        page = await asyncio.to_thread(_fetch_page_text, url)
    except Exception as e:  # noqa: BLE001
        return f"❌ `{short_url}`\n`{str(e)[:200]}`"
    if not page.get("body") and not page.get("description"):
        return f"❌ `{short_url}` — no readable text on this page"
    ai = await _ai_summarise(_tldr_prompt(page, lang))
    head = f"🌐 [{page['title'] or short_url}]({url})"
    return head + ("\n\n" + ai if ai else f"\n\n_{page.get('description','')[:400]}_")


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


# ────────── Language detection / target-lang resolution for .tl ──────────
# User-facing names (English + Persian) → ISO 639-1 code. Order doesn't matter
# but multi-word entries must be looked up before single-word ones (see
# `_resolve_target_lang` which scans 3→2→1 word prefixes).
LANG_ALIASES: dict[str, str] = {
    # English names + ISO codes
    "english": "en", "en": "en", "eng": "en",
    "persian": "fa", "farsi": "fa", "fa": "fa", "per": "fa", "fas": "fa",
    "arabic": "ar", "ar": "ar",
    "spanish": "es", "es": "es",
    "french": "fr", "fr": "fr",
    "german": "de", "de": "de",
    "italian": "it", "it": "it",
    "russian": "ru", "ru": "ru",
    "turkish": "tr", "tr": "tr",
    "japanese": "ja", "ja": "ja", "jp": "ja", "jpn": "ja",
    "chinese": "zh", "zh": "zh", "cn": "zh", "chn": "zh", "mandarin": "zh",
    "korean": "ko", "ko": "ko", "kr": "ko", "kor": "ko",
    "hindi": "hi", "hi": "hi",
    "urdu": "ur", "ur": "ur",
    "dutch": "nl", "nl": "nl",
    "portuguese": "pt", "pt": "pt",
    "swedish": "sv", "sv": "sv",
    "polish": "pl", "pl": "pl",
    "kurdish": "ku", "ku": "ku",
    "azerbaijani": "az", "az": "az", "azeri": "az",
    "ukrainian": "uk", "uk": "uk",
    "greek": "el", "el": "el",
    "hebrew": "he", "he": "he",
    "vietnamese": "vi", "vi": "vi",
    "thai": "th", "th": "th",
    "indonesian": "id", "id": "id",
    # Persian (Farsi) names
    "انگلیسی": "en", "اینگلیسی": "en", "آمریکایی": "en",
    "فارسی": "fa",
    "عربی": "ar",
    "اسپانیایی": "es", "اسپانیولی": "es", "اسپانیش": "es",
    "فرانسوی": "fr", "فرانسه": "fr", "فرانسه‌ای": "fr",
    "آلمانی": "de", "آلمان": "de",
    "ایتالیایی": "it", "ایتالیا": "it",
    "روسی": "ru", "روسیه": "ru",
    "ترکی": "tr", "ترکی استانبولی": "tr",
    "ژاپنی": "ja", "ژاپن": "ja",
    "چینی": "zh", "چین": "zh", "ماندارین": "zh",
    "کره‌ای": "ko", "کره ای": "ko", "کره": "ko",
    "هندی": "hi", "هند": "hi",
    "اردو": "ur",
    "هلندی": "nl", "هلند": "nl",
    "پرتغالی": "pt", "پرتغال": "pt",
    "سوئدی": "sv", "سوئد": "sv",
    "لهستانی": "pl", "لهستان": "pl",
    "کردی": "ku",
    "آذری": "az", "ترکی آذری": "az", "آذربایجانی": "az",
    "اوکراینی": "uk",
    "یونانی": "el",
    "عبری": "he",
    "ویتنامی": "vi",
    "تایلندی": "th",
    "اندونزیایی": "id",
}


def _resolve_target_lang(s: str) -> tuple[str | None, str]:
    """If `s` starts with a known language token (English/Persian name or ISO
    code), return (iso_code, remaining_text). Otherwise return (None, s).

    Scans the first 3, then 2, then 1 word(s) so multi-word names like
    'ترکی استانبولی' resolve before their first word alone.
    """
    if not s:
        return None, ""
    s = s.strip()
    if not s:
        return None, ""
    # Match against the longest possible leading n-word prefix
    words = s.split()
    for n in (min(3, len(words)), 2, 1):
        if n > len(words):
            continue
        candidate = " ".join(words[:n]).lower().strip(".,!?:;")
        if candidate in LANG_ALIASES:
            rest = " ".join(words[n:]).strip()
            return LANG_ALIASES[candidate], rest
    return None, s


def _is_persian_text(text: str) -> bool:
    """True if `text` is predominantly Persian/Arabic script. Used by .tl to
    decide auto fa↔en direction when the user didn't specify a target."""
    if not text:
        return False
    persian = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    # Tie or no letters at all → treat as Persian (so we send to English),
    # since the user is Persian-speaking by default.
    return persian >= latin and persian > 0


# ────────── Image aspect-ratio helpers ──────────
# Aspect ratios supported by Gemini Nano Banana / Pro Image models
SUPPORTED_AR: tuple[str, ...] = (
    "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
    "16:9", "9:16", "21:9", "1:4", "4:1", "1:8", "8:1",
)

# Friendly aliases (English & Persian) for the most common ratios
AR_ALIASES: dict[str, str] = {
    # square
    "square": "1:1", "sq": "1:1", "مربع": "1:1", "مربعی": "1:1",
    # landscape / wide
    "landscape": "16:9", "wide": "16:9", "horizontal": "16:9", "hd": "16:9",
    "افقی": "16:9", "عریض": "16:9", "منظره": "16:9",
    # portrait / story
    "portrait": "9:16", "vertical": "9:16", "story": "9:16", "reel": "9:16", "tall": "9:16",
    "عمودی": "9:16", "استوری": "9:16", "ریل": "9:16", "پرتره": "9:16",
    # cinematic
    "cinematic": "21:9", "cinema": "21:9", "ultrawide": "21:9", "سینمایی": "21:9",
    # photo
    "photo": "3:2", "dslr": "3:2", "عکس": "3:2",
    # classic
    "classic": "4:3", "tv": "4:3",
}


def _parse_aspect_ratio(s: str | None) -> str | None:
    """Return a valid 'W:H' string or None if `s` is not recognized."""
    if not s:
        return None
    s = s.strip().lower().replace("×", ":").replace("x", ":")
    if s in AR_ALIASES:
        return AR_ALIASES[s]
    if s in SUPPORTED_AR:
        return s
    # Tolerate "16x9", "16 9", "9÷16" etc.
    m = re.match(r"^\s*(\d+)\s*[:/x×\-\s]\s*(\d+)\s*$", s)
    if m:
        canonical = f"{int(m.group(1))}:{int(m.group(2))}"
        if canonical in SUPPORTED_AR:
            return canonical
    return None


def _extract_ar_flag(text: str) -> tuple[str | None, str]:
    """Pull an inline `--ar 16:9` / `--16:9` / `--landscape` flag out of `text`.

    Returns (aspect_ratio_or_None, cleaned_prompt_without_flag).
    """
    # `--ar VALUE`  /  `-ar VALUE`
    m = re.search(r"(?:^|\s)-{1,2}ar\s+(\S+)", text, re.I)
    if m:
        ar = _parse_aspect_ratio(m.group(1))
        if ar:
            return ar, (text[:m.start()] + " " + text[m.end():]).strip()
    # `--16:9` / `--landscape` shorthand
    m = re.search(r"(?:^|\s)-{1,2}([\w:×x]+)\b", text)
    if m:
        ar = _parse_aspect_ratio(m.group(1))
        if ar:
            return ar, (text[:m.start()] + " " + text[m.end():]).strip()
    return None, text


def _friendly_image_error(err: str) -> tuple[str, str]:
    """Map a raw Gemini/litellm error to a (friendly_en, friendly_fa) message."""
    e = (err or "").lower()
    if "budget has been exceeded" in e or "budget" in e and "exceeded" in e:
        return (
            "💸 Emergent key budget exceeded. Go to Emergent → Profile → Universal Key to top up.",
            "💸 اعتبار کلید Emergent تموم شده. از Profile → Universal Key شارژ کن.",
        )
    if "safety" in e or "blocked" in e or "content policy" in e or "no images returned" in e or "prohibited" in e:
        return (
            "🛡 Prompt blocked by Gemini's safety filter.\n"
            "Try: remove brand names, avoid detailed real-person descriptions (age/skin/face), "
            "use generic styling words instead.",
            "🛡 پرامپت توسط فیلتر امنیتی Gemini مسدود شد.\n"
            "پیشنهاد: نام برند (مرسدس، نایک، …) رو حذف کن، توصیف دقیق چهره/سن/پوست شخص واقعی نده، "
            "از کلمات کلی‌تر و سبک هنری استفاده کن.",
        )
    if "rate" in e and "limit" in e:
        return ("⏳ Rate limit — wait a few seconds and try again.",
                "⏳ محدودیت تعداد درخواست — چند ثانیه صبر کن دوباره امتحان کن.")
    if "invalid_api_key" in e or "authentication" in e or "unauthorized" in e or "401" in e:
        return ("🔑 Invalid EMERGENT_LLM_KEY. Check your .env file.",
                "🔑 EMERGENT_LLM_KEY نامعتبره. فایل .env رو چک کن.")
    if "timeout" in e or "timed out" in e:
        return ("⌛ Gemini timed out. Try again in a moment.",
                "⌛ Gemini پاسخ نداد. چند لحظه صبر کن.")
    # Generic fallback — show the first useful piece of the error
    snippet = err.split("\n")[0][:180]
    return (f"❌ Image generation failed: `{snippet}`",
            f"❌ تولید تصویر ناموفق بود: `{snippet}`")


# ────────── LLM helpers ──────────
async def _generate_image(prompt: str, aspect_ratio: str | None = None) -> tuple[bytes | None, str | None]:
    """Generate an image. Returns (image_bytes, error_msg) — exactly one is None."""
    ready, ai_err = _ai_ready()
    if not ready:
        return None, ai_err or "AI not configured"
    if not prompt.strip():
        return None, "empty prompt"
    model_name = config.get("image_model", "gemini-3.1-flash-image-preview")
    ar = aspect_ratio or config.get("image_aspect_ratio", "1:1")
    try:
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"image-{time.time_ns()}",
                system_message="You are an expert image generator. Create high-quality, detailed images based on the user's prompt.",
            )
            .with_model("gemini", model_name)
            .with_params(modalities=["image", "text"],
                         image_config={"aspect_ratio": ar})
        )
        _text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
        if not images:
            log.warning("Image gen: no images returned (likely safety filter)")
            return None, "no images returned (likely content blocked by safety filter)"
        return base64.b64decode(images[0]["data"]), None
    except Exception as e:  # noqa: BLE001
        log.error(f"Image gen error: {e}")
        return None, str(e)


async def _edit_image(image_bytes: bytes, edit_prompt: str, aspect_ratio: str | None = None) -> tuple[bytes | None, str | None]:
    """Edit an image. Returns (image_bytes, error_msg)."""
    ready, ai_err = _ai_ready()
    if not ready:
        return None, ai_err or "AI not configured"
    if not edit_prompt.strip() or not image_bytes:
        return None, "empty prompt or image"
    model_name = config.get("image_model", "gemini-3.1-flash-image-preview")
    ar = aspect_ratio or config.get("image_aspect_ratio", "1:1")
    try:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"imgedit-{time.time_ns()}",
                system_message="You are an expert image editor. Edit the given reference image based on the user's instructions while preserving the main subject's identity unless told otherwise.",
            )
            .with_model("gemini", model_name)
            .with_params(modalities=["image", "text"],
                         image_config={"aspect_ratio": ar})
        )
        msg = UserMessage(text=edit_prompt, file_contents=[ImageContent(image_b64)])
        _text, images = await chat.send_message_multimodal_response(msg)
        if not images:
            log.warning("Image edit: no images returned (likely safety filter)")
            return None, "no images returned (likely content blocked by safety filter)"
        return base64.b64decode(images[0]["data"]), None
    except Exception as e:  # noqa: BLE001
        log.error(f"Image edit error: {e}")
        return None, str(e)


async def _combine_images(images_b64: list[str], prompt: str,
                          aspect_ratio: str | None = None) -> tuple[bytes | None, str | None]:
    """Combine/blend multiple reference images into one. Returns (bytes, error)."""
    ready, ai_err = _ai_ready()
    if not ready:
        return None, ai_err or "AI not configured"
    if len(images_b64) < 2:
        return None, "need at least two images"
    model_name = config.get("image_model", "gemini-3.1-flash-image-preview")
    ar = aspect_ratio or config.get("image_aspect_ratio", "1:1")
    try:
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"imgmix-{time.time_ns()}",
                system_message="You are an expert image compositor. You blend and combine multiple reference images into a single, coherent, high-quality image.",
            )
            .with_model("gemini", model_name)
            .with_params(modalities=["image", "text"],
                         image_config={"aspect_ratio": ar})
        )
        contents = [ImageContent(b) for b in images_b64]
        msg = UserMessage(text=prompt, file_contents=contents)
        _text, images = await chat.send_message_multimodal_response(msg)
        if not images:
            log.warning("Image combine: no images returned (likely safety filter)")
            return None, "no images returned (likely content blocked by safety filter)"
        return base64.b64decode(images[0]["data"]), None
    except Exception as e:  # noqa: BLE001
        log.error(f"Image combine error: {e}")
        return None, str(e)


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


# ────────── Text-to-Speech (.say) helpers ──────────
TTS_VOICES: tuple[str, ...] = (
    "alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer",
)
TTS_MODELS: tuple[str, ...] = ("tts-1", "tts-1-hd")


def _tts_ready() -> tuple[bool, str]:
    if not TTS_LIB_OK:
        return False, "emergentintegrations TTS module not available"
    if not EMERGENT_LLM_KEY:
        return False, "EMERGENT_LLM_KEY not set in .env"
    return True, ""


def _extract_voice_flag(text: str) -> tuple[str | None, str]:
    """Pull an inline `-v onyx` / `--voice onyx` flag out of `text`.
    Returns (voice_or_None, cleaned_text)."""
    m = re.search(r"(?:^|\s)-{1,2}v(?:oice)?\s+([A-Za-z]+)", text, re.I)
    if m:
        v = m.group(1).lower()
        if v in TTS_VOICES:
            return v, (text[:m.start()] + " " + text[m.end():]).strip()
    return None, text


def _chunk_text(text: str, size: int) -> list[str]:
    """Split `text` into <=`size`-char chunks on word boundaries (for the
    OpenAI TTS 4096-char limit)."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    cur = ""
    for word in text.split(" "):
        if len(cur) + len(word) + 1 > size:
            if cur:
                chunks.append(cur)
            cur = word[:size]
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text[:size]]


def _opus_duration(data: bytes) -> int:
    """Estimate an ogg-opus clip's duration (seconds) from the last Ogg page's
    granule position. Opus granule positions are counted at 48 kHz."""
    try:
        idx = data.rfind(b"OggS")
        if idx < 0 or idx + 14 > len(data):
            return 0
        granule = int.from_bytes(data[idx + 6:idx + 14], "little")
        return max(0, round(granule / 48000))
    except Exception:  # noqa: BLE001
        return 0


def _friendly_tts_error(err: str) -> tuple[str, str]:
    """Map a raw TTS error to a (friendly_en, friendly_fa) message."""
    e = (err or "").lower()
    if "budget" in e and "exceeded" in e:
        return (
            "💸 Emergent key budget exceeded. Top up in Profile → Universal Key.",
            "💸 اعتبار کلید Emergent تموم شده. از Profile → Universal Key شارژ کن.",
        )
    if "rate" in e and "limit" in e:
        return ("⏳ Rate limit — wait a few seconds and try again.",
                "⏳ محدودیت تعداد درخواست — چند ثانیه صبر کن.")
    if any(k in e for k in ("invalid_api_key", "authentication", "unauthorized", "401")):
        return ("🔑 Invalid EMERGENT_LLM_KEY. Check your .env file.",
                "🔑 EMERGENT_LLM_KEY نامعتبره. فایل .env رو چک کن.")
    if "timeout" in e or "timed out" in e:
        return ("⌛ TTS timed out. Try again in a moment.",
                "⌛ سرویس صدا پاسخ نداد. چند لحظه صبر کن.")
    snippet = err.split("\n")[0][:180]
    return (f"❌ Voice generation failed: `{snippet}`",
            f"❌ ساخت ویس ناموفق بود: `{snippet}`")


async def _tts_generate(text: str, voice: str, model: str,
                        fmt: str = "opus") -> tuple[bytes | None, str | None]:
    """Generate speech audio. Returns (audio_bytes, error_msg) — exactly one is None."""
    ready, err = _tts_ready()
    if not ready:
        return None, err
    if not text.strip():
        return None, "empty text"
    try:
        tts = OpenAITextToSpeech(api_key=EMERGENT_LLM_KEY)
        audio = await tts.generate_speech(
            text=text, model=model, voice=voice, response_format=fmt)
        if not audio:
            return None, "no audio returned"
        return audio, None
    except Exception as e:  # noqa: BLE001
        log.error(f"TTS error: {e}")
        return None, str(e)


# ────────── URL Uploader (.up) helpers ──────────
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB (normal Telegram account limit)

_UP_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "heic"}
_UP_VIDEO_EXTS = {"mp4", "mkv", "mov", "webm", "avi", "m4v", "mpg", "mpeg", "wmv", "flv"}
_UP_AUDIO_EXTS = {"mp3", "m4a", "ogg", "oga", "opus", "flac", "wav", "aac", "wma"}


def _human_size(n) -> str:
    """Human-readable byte size, e.g. 12.4 MB."""
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _progress_bar(pct) -> str:
    """10-segment progress bar string."""
    pct = max(0, min(100, int(pct)))
    filled = pct // 10
    return "█" * filled + "░" * (10 - filled)


def _guess_upload_filename(url: str, headers, mime: str = "") -> str:
    """Best-effort filename from Content-Disposition → URL path → mime fallback."""
    name = ""
    cd = ""
    try:
        cd = headers.get("Content-Disposition") or ""
    except Exception:  # noqa: BLE001
        cd = ""
    if cd:
        m = re.search(r"filename\*=(?:UTF-8'')?([^;\n]+)", cd, re.I) or \
            re.search(r'filename="?([^";\n]+)"?', cd, re.I)
        if m:
            name = urllib.parse.unquote(m.group(1).strip().strip('"'))
    if not name:
        path = urllib.parse.urlparse(url).path
        name = urllib.parse.unquote(os.path.basename(path))
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip().strip(".")
    if not name:
        name = "file"
    # Append an extension from the mime type when the name has none
    if "." not in name and mime:
        ext = mimetypes.guess_extension(mime.split(";")[0].strip())
        if ext:
            name += ext
    return name[:200]


def _categorize_upload(name: str, mime: str) -> str:
    """Return 'image' / 'video' / 'audio' / 'document' for smart sending."""
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    mime = (mime or "").lower()
    if ext in _UP_IMAGE_EXTS or mime.startswith("image/"):
        return "image"
    if ext in _UP_VIDEO_EXTS or mime.startswith("video/"):
        return "video"
    if ext in _UP_AUDIO_EXTS or mime.startswith("audio/"):
        return "audio"
    return "document"


def _build_upload_caption(info: dict, category: str) -> str:
    icon = {"image": "🖼", "video": "🎬", "audio": "🎵", "document": "📄"}.get(category, "📦")
    domain = urllib.parse.urlparse(info.get("url", "")).netloc or "—"
    return t("up_caption",
             icon=icon,
             name=info["name"],
             type=(info.get("mime") or category),
             size=_human_size(info["size"]),
             src=domain)


async def _safe_edit(msg, text) -> None:
    try:
        await msg.edit(text)
    except Exception:  # noqa: BLE001
        pass


async def _download_url_file(url: str, tmpdir: str, status) -> tuple[dict | None, str | None]:
    """Stream-download `url` to `tmpdir`, enforcing MAX_UPLOAD_SIZE, with periodic
    progress edits on `status`. Returns (info_dict, error_msg)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0 Safari/537.36"),
        "Accept": "*/*",
    })
    try:
        resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=30)
    except Exception as e:  # noqa: BLE001
        return None, t("up_failed", e=str(e)[:200])

    try:
        clen = int(resp.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        clen = 0
    if clen and clen > MAX_UPLOAD_SIZE:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
        return None, t("up_too_big", size=_human_size(clen), max=_human_size(MAX_UPLOAD_SIZE))

    mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    filename = _guess_upload_filename(url, resp.headers, mime)
    path = os.path.join(tmpdir, filename)

    downloaded = 0
    last_edit = 0.0
    chunk_size = 1024 * 1024  # 1 MB
    try:
        with open(path, "wb") as f:
            while True:
                chunk = await asyncio.to_thread(resp.read, chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded > MAX_UPLOAD_SIZE:
                    return None, t("up_too_big", size="> 2 GB", max=_human_size(MAX_UPLOAD_SIZE))
                now = time.time()
                if now - last_edit >= 3:
                    last_edit = now
                    if clen:
                        pct = downloaded * 100 // clen
                        await _safe_edit(status, t("up_downloading_pct",
                                                   bar=_progress_bar(pct), pct=pct,
                                                   done=_human_size(downloaded),
                                                   total=_human_size(clen)))
                    else:
                        await _safe_edit(status, t("up_downloading",
                                                   done=_human_size(downloaded)))
    except Exception as e:  # noqa: BLE001
        return None, t("up_failed", e=str(e)[:200])
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass

    if downloaded == 0:
        return None, t("up_failed", e="empty response (0 bytes)")
    return {"path": path, "name": filename, "size": downloaded, "mime": mime, "url": url}, None


# ────────── Music Helpers (Universal Downloader) ──────────
# Platform detection patterns. Order matters — first match wins.
_MUSIC_PLATFORMS: list[tuple[str, re.Pattern, bool]] = [
    # (name, regex, is_drm_protected)
    # Only `music.youtube.com` — regular YouTube video links are intentionally
    # excluded so the bot doesn't auto-convert every video into an audio file.
    ("youtube",   re.compile(r"https?://music\.youtube\.com/(?:watch\?[^\s]*v=|playlist\?list=)[\w\-]+(?:[?&][^\s]*)?", re.I), False),
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
    "youtube": "YouTube Music",
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


def _to_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _is_chat_allowed(chat_id) -> bool:
    """True if `chat_id` (in any representation) is in the allowed_groups whitelist."""
    allowed = config.get("allowed_groups", []) or []
    if not allowed:
        return False
    variants = _chat_id_variants(chat_id)
    return any(_to_int(a) in variants for a in allowed)


def _whitelist_contains(cid, lst) -> bool:
    variants = _chat_id_variants(cid)
    return any(_to_int(x) in variants for x in lst)


def _whitelist_without(cid, lst) -> list:
    variants = _chat_id_variants(cid)
    return [x for x in lst if _to_int(x) not in variants]


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


def _http_json(url: str, timeout: int = 15) -> dict:
    """GET a JSON endpoint. Blocking — run in a thread."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(300_000).decode("utf-8", errors="ignore"))


def _clean_query(q: str) -> str:
    """Normalize a metadata string into a clean search query."""
    q = html.unescape(q or "").replace("\xa0", " ")
    # Drop noise like "(Official Video)", "[Lyrics]", "(HD)" …
    q = re.sub(r"[\(\[][^)\]]*(?:official|lyric|lyrics|video|audio|visualizer|hd|4k|mv)[^)\]]*[\)\]]",
               "", q, flags=re.I)
    q = re.sub(r"\s*-\s*(?:Single|EP)\s*$", "", q, flags=re.I)
    q = re.sub(r"\s{2,}", " ", q)
    return q.strip(" -–—·|").strip()


def _apple_lookup(url: str) -> str | None:
    """Resolve an Apple Music URL to 'Artist - Title' via the public iTunes
    Lookup API (no auth, reliable — page scraping on music.apple.com is flaky)."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    ids: list[str] = []
    if qs.get("i"):  # album link pointing at a specific track: ?i=<track_id>
        ids.append(qs["i"][0])
    ids += [i for i in re.findall(r"/(\d{5,})", parsed.path) if i not in ids][::-1]
    mc = re.match(r"^/([a-z]{2})/", parsed.path, re.I)
    country = mc.group(1) if mc else "us"
    for id_ in ids:
        try:
            data = _http_json(f"https://itunes.apple.com/lookup?id={id_}&country={country}")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[music] iTunes lookup failed for {id_}: {e}")
            continue
        for r in (data or {}).get("results", []):
            artist = (r.get("artistName") or "").strip()
            track = (r.get("trackName") or r.get("collectionName") or "").strip()
            if artist and track:
                return f"{artist} - {track}"
    return None


def _deezer_lookup(url: str) -> str | None:
    """Resolve a Deezer track URL to 'Artist - Title' via the public Deezer API."""
    m = re.search(r"/track/(\d+)", url)
    if not m:
        return None
    try:
        data = _http_json(f"https://api.deezer.com/track/{m.group(1)}")
    except Exception as e:  # noqa: BLE001
        log.debug(f"[music] Deezer API failed: {e}")
        return None
    title = (data.get("title") or "").strip()
    artist = ((data.get("artist") or {}).get("name") or "").strip()
    if artist and title:
        return f"{artist} - {title}"
    return title or None


def _youtube_title_query(url: str) -> str | None:
    """Get 'Artist - Title' for a YouTube / YouTube Music video via oEmbed.
    Works even when video downloads are blocked for the server's IP."""
    try:
        data = _http_json(
            "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe=""))
    except Exception as e:  # noqa: BLE001
        log.debug(f"[music] YouTube oEmbed failed: {e}")
        return None
    title = _clean_query(data.get("title") or "")
    author = re.sub(r"\s*-\s*Topic$", "", (data.get("author_name") or "").strip()).strip()
    if not title:
        return None
    if author and author.lower() not in title.lower():
        return f"{author} - {title}"
    return title


def _fetch_drm_metadata(url: str, platform: str) -> str | None:
    """For DRM-protected platforms (Spotify, Deezer, Apple Music, Tidal),
    fetch track metadata and return a search query of the form 'Artist - Title'.
    Returns None on failure.

    Order of strategies:
      0. Official public lookup APIs (iTunes / Deezer) — most reliable
      1. Spotify oEmbed + embed page
      2. OpenGraph meta tags from the page itself (universal fallback)
    """
    # ── Strategy 0: official public APIs ──
    if platform == "apple":
        q = _apple_lookup(url)
        if q:
            return _clean_query(q)
    elif platform == "deezer":
        q = _deezer_lookup(url)
        if q:
            return _clean_query(q)

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
                    emb_page = resp2.read(200_000).decode("utf-8", errors="ignore")
                m = re.search(r'"artists":\s*\[\s*\{\s*"name"\s*:\s*"([^"]+)"', emb_page)
                if m:
                    artist = m.group(1).strip()
                if not title:
                    m2 = re.search(r'"name"\s*:\s*"([^"]+)"', emb_page)
                    if m2:
                        title = m2.group(1).strip()
            except Exception as e:  # noqa: BLE001
                log.debug(f"[music] Spotify embed parse: {e}")
            if artist and title:
                return _clean_query(f"{artist} - {title}")
            if title:
                return _clean_query(title)
        except Exception as e:  # noqa: BLE001
            log.warning(f"[music] Spotify oEmbed failed: {e}")

    # ── Strategy 2: OpenGraph meta tags from main URL (universal fallback) ──
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
            page = resp.read(300_000).decode("utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        log.warning(f"[music] DRM metadata fetch failed ({platform}): {e}")
        return None

    def _meta(prop: str) -> str:
        # Match both orderings: property=...content=...  AND  content=...property=...
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            page, re.IGNORECASE,
        )
        if not m:
            m = re.search(
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
                page, re.IGNORECASE,
            )
        return html.unescape(m.group(1).strip()) if m else ""

    og_title = _meta("og:title")
    og_desc = _meta("og:description")

    # "TITLE by ARTIST on Apple Music" style titles → 'ARTIST - TITLE'
    m = re.match(r"^(.+?)\s+by\s+(.+?)\s+on\s+(?:Apple\s*Music|Spotify|Deezer|TIDAL)\b",
                 og_title, re.IGNORECASE)
    if m:
        return _clean_query(f"{m.group(2)} - {m.group(1)}")

    # Tidal & friends already use 'Artist - Title' as og:title — use it as-is
    if og_title and " - " in og_title:
        return _clean_query(og_title)

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
                    r"listen\s*to|year|duration\b.*)$",
                    re.IGNORECASE,
                )
                year_rx = re.compile(r"^\d{4}$")
                # Split on bullets OR space-dash-space (but not unicode dashes inside names)
                parts = [p.strip() for p in re.split(r"\s*[·•]\s*|\s+-\s+", og_desc) if p.strip()]
                parts = [p for p in parts
                         if not generic.match(p) and not year_rx.match(p)
                         and "listen to" not in p.lower()]
                if parts:
                    artist = parts[0]

    artist = (artist or "").strip().strip("-—–·")
    title = (title or "").strip().strip("-—–·")
    # Strip trailing platform suffix sometimes present in titles
    title = re.sub(r"\s*[-–|]\s*(Spotify|Deezer|Apple Music|Tidal)\s*$", "", title, flags=re.I)

    if artist and title:
        return _clean_query(f"{artist} - {title}")
    if title:
        return _clean_query(title)
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


def _music_download_sync(target: str, tmpdir: str) -> dict | None:
    """Download audio from any platform supported by yt-dlp.

    `target` can be:
      • a direct URL (SoundCloud / YouTube / Bandcamp / Mixcloud / ...)
      • a `ytsearch1:` / `scsearch1:` query string (DRM platform fallback)

    Prefers m4a/mp3 so the result is a proper audio file even without ffmpeg;
    converts to mp3 when ffmpeg is available.
    """
    have_ffmpeg = shutil.which("ffmpeg") is not None
    opts = {
        # m4a/mp3 first → playable audio file even when ffmpeg is missing
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
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
    audio_exts = {".mp3", ".m4a", ".opus", ".ogg", ".oga", ".aac",
                  ".wav", ".flac", ".webm", ".mka"}
    # Some sources (esp. YouTube on restricted IPs) only offer progressive
    # video containers — the audio inside still plays fine in Telegram.
    video_exts = {".mp4", ".m4v", ".mov", ".mkv"}
    audio_files, video_files = [], []
    for name in os.listdir(tmpdir):
        if name.endswith((".part", ".ytdl")) or name == "cover.jpg":
            continue
        ext = os.path.splitext(name)[1].lower()
        path = os.path.join(tmpdir, name)
        if ext in audio_exts:
            audio_files.append((os.path.getsize(path), path))
        elif ext in video_exts:
            video_files.append((os.path.getsize(path), path))
    candidates = audio_files or video_files
    if not candidates:
        return None
    filepath = max(candidates)[1]  # largest matching file
    # Cover art for Telegram audio thumbnail
    thumb_path = None
    thumb_url = info.get("thumbnail") or ""
    if thumb_url.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        try:
            thumb_path = os.path.join(tmpdir, "cover.jpg")
            req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(thumb_path, "wb") as f:
                f.write(resp.read(5_000_000))
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
                                   reply_to_msg_id=None, force_reply: bool = False,
                                   fallback_urls: list[str] | None = None) -> bool:
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
                # Skip short uploads (often 30s previews/snippets)
                full = [r for r in sc_results if (r.get("duration") or 0) >= 60]
                targets += [r["url"] for r in (full or sc_results)[:3]]
            except Exception as e:  # noqa: BLE001
                log.warning(f"[music] SoundCloud fallback search failed: {e}")
                targets.append(f"scsearch1:{query}")
        else:
            targets = [url]
            # Allow callers (e.g. `.sc <number>`) to provide additional candidates
            # to try when the primary URL is DRM-protected (SoundCloud Go+ / paid
            # tracks raise `This video is DRM protected` and have no audio stream).
            if fallback_urls:
                for fb in fallback_urls:
                    if fb and fb != url and fb not in targets:
                        targets.append(fb)

        info = None
        last_err: Exception | None = None

        async def _try_targets(tgts) -> dict | None:
            nonlocal tmpdir, last_err
            for tgt in tgts:
                tmpdir = tempfile.mkdtemp(prefix="bidar_music_")
                try:
                    got = await asyncio.to_thread(_music_download_sync, tgt, tmpdir)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.warning(f"[music] download failed for target `{tgt[:80]}`: {e}")
                    got = None
                if got:
                    return got
                shutil.rmtree(tmpdir, ignore_errors=True)
                tmpdir = None
            return None

        info = await _try_targets(targets)

        # Direct YouTube/YT-Music links often can't be downloaded from server
        # IPs (403 / video-only). Resolve the title via oEmbed and look for the
        # same track on SoundCloud instead.
        if not info and platform == "youtube":
            query = await asyncio.to_thread(_youtube_title_query, url)
            if query:
                log.info(f"[music] YouTube blocked → SoundCloud fallback: {query}")
                try:
                    sc_results = await asyncio.to_thread(_sc_search_sync, query)
                    # Skip short uploads (often 30s previews/snippets)
                    full = [r for r in sc_results if (r.get("duration") or 0) >= 60]
                    fb_targets = [r["url"] for r in (full or sc_results)[:3]]
                except Exception as e:  # noqa: BLE001
                    log.warning(f"[music] SoundCloud fallback search failed: {e}")
                    fb_targets = [f"scsearch1:{query}"]
                if fb_targets:
                    info = await _try_targets(fb_targets)

        if not info:
            raw_err = str(last_err) if last_err else "no audio found"
            # Friendlier hint for SoundCloud Go+ / paid DRM-protected tracks
            if "DRM protected" in raw_err or "drm" in raw_err.lower():
                err_short = (
                    "all tried tracks are DRM-protected (SoundCloud Go+/paid). "
                    "Pick another search result or try a different query."
                )
            else:
                err_short = raw_err[:200]
            await status_msg.edit(t("music_failed", platform=label, e=err_short))
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
def _is_supported_image_bytes(data: bytes) -> bool:
    """True if `data` looks like a JPEG/PNG/GIF/WEBP — formats Gemini Vision
    accepts natively. Animated stickers (.tgs) and video stickers (.webm) are
    rejected so we don't waste a vision call on them."""
    if not data or len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":  # JPEG (any variant)
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


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
    image_b64: str | None = None
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
            if replied:
                tt = (replied.raw_text or replied.text or "").strip()
                if tt:
                    target_text = tt[:500]
                # Vision support: if the replied message contains an image
                # (photo / image document / static sticker), download it and
                # attach to the prompt so the model can SEE and reason about it.
                has_visual = bool(
                    replied.photo
                    or (replied.document and
                        (getattr(replied.document, "mime_type", "") or "")
                        .startswith("image/"))
                )
                if has_visual:
                    try:
                        img_bytes = await client.download_media(replied, file=bytes)
                        if (img_bytes and isinstance(img_bytes, bytes)
                                and _is_supported_image_bytes(img_bytes)):
                            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                            log.info(f"[.r] attached image to prompt ({len(img_bytes)//1024}KB)")
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"cmd_r: image download failed: {e}")
        except Exception:  # noqa: BLE001
            pass

    context_str = "\n".join(context_lines) if context_lines else "(no recent context)"
    chat_type = "private chat" if event.is_private else "group chat"

    if image_b64:
        # Image-aware system prompt: model gets a picture + (optional) question
        system_msg = (
            f"You are replying as 'You' in a real Telegram {chat_type}. The user has "
            "replied to a message that contains an IMAGE which is attached to this prompt. "
            "Look at the image carefully and use it to inform your reply. "
            "If the user asked a question, answer it precisely based on what's actually "
            "visible in the image. If there's no explicit question, write a natural, "
            "context-appropriate reply that meaningfully reacts to the image and the "
            "ongoing conversation. "
            "Match the language of the conversation (Persian → Persian, English → English). "
            "Do NOT introduce yourself as AI, bot, or assistant. "
            "Output ONLY the message text — no quotes, no labels, no preamble."
        )
    else:
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
    if image_b64:
        parts.append("\n(An image is attached to this prompt — examine it carefully.)")
    if hint:
        parts.append(f"\n(Additional instruction / question: {hint})")
    parts.append("\nNow write the reply:")
    user_prompt = "\n".join(parts)

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"genreply-{time.time_ns()}",
            system_message=system_msg,
        ).with_model(_infer_provider(config["ai_model"]), config["ai_model"])
        if image_b64 and ImageContent is not None:
            user_msg = UserMessage(text=user_prompt,
                                   file_contents=[ImageContent(image_b64)])
        else:
            user_msg = UserMessage(text=user_prompt)
        resp = await chat.send_message(user_msg)
        reply_text = str(resp).strip()
        if (reply_text.startswith('"') and reply_text.endswith('"')) or \
           (reply_text.startswith("«") and reply_text.endswith("»")):
            reply_text = reply_text[1:-1].strip()
        if not reply_text:
            await event.edit(t("r_no_response"))
            return
        stats["ai_replies"] += 1
        await event.edit(reply_text)
        log.info(
            f"[.r] generated in chat={event.chat_id} len={len(reply_text)} "
            f"vision={'yes' if image_b64 else 'no'}"
        )
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
    """Smart translator with auto fa↔en detection.

    Behaviour:
      .tl <text>            → Persian text → English, anything else → Persian
      .tl <lang> <text>     → translate to <lang> (e.g. `.tl عربی hello`)
      .tl  (reply)          → auto fa↔en on the replied message
      .tl <lang> (reply)    → translate replied message to <lang>
                              (e.g. reply + `.tl عربی`)
    """
    raw_arg = (event.pattern_match.group(1) or "").strip()
    explicit_target: str | None = None
    arg_text = raw_arg

    if raw_arg:
        lang_code, remaining = _resolve_target_lang(raw_arg)
        if lang_code:
            explicit_target = lang_code
            arg_text = remaining

    # Resolve source text — inline arg wins over replied message
    if arg_text:
        source_text = arg_text
    elif event.is_reply:
        try:
            replied = await event.get_reply_message()
            source_text = ((replied.raw_text or replied.text or "") if replied else "").strip()
            if not source_text:
                await event.edit(t("tl_no_text"))
                return
        except Exception as e:  # noqa: BLE001
            await event.edit(t("tl_reply_error", e=str(e)))
            return
    else:
        await event.edit(t("tl_usage", p=CMD_PREFIX, t="auto fa↔en"))
        return

    # Auto-detect direction when user didn't specify a target language
    target = explicit_target or ("en" if _is_persian_text(source_text) else "fa")

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
                           m=config.get("image_model", "gemini-3.1-flash-image-preview"),
                           ar=config.get("image_aspect_ratio", "1:1")))
        return
    # Extract optional `--ar` / `--<alias>` flag from the prompt
    ar_override, prompt = _extract_ar_flag(prompt.strip())
    if not prompt:
        await event.edit(t("img_usage",
                           p=CMD_PREFIX,
                           m=config.get("image_model", "gemini-3.1-flash-image-preview"),
                           ar=config.get("image_aspect_ratio", "1:1")))
        return
    effective_ar = ar_override or config.get("image_aspect_ratio", "1:1")
    msg = await event.edit(t("img_processing", p=prompt[:100], ar=effective_ar))
    img_bytes, err = await _generate_image(prompt, aspect_ratio=ar_override)
    if not img_bytes:
        en, fa = _friendly_image_error(err or "")
        await msg.edit(fa if config.get("bot_lang", "en") == "fa" else en)
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
    except Exception as e:  # noqa: BLE001
        log.error(f"Send image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
        return
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    # Image sent successfully — remove the processing message (guarded so a
    # transient delete failure never leaves it behind or mislabels the send).
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
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


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}imgsize(?:\s+(\S+))?$"))
@owner_only
async def cmd_imgsize(event):
    arg = event.pattern_match.group(1)
    current = config.get("image_aspect_ratio", "1:1")
    if arg is None:
        await event.edit(t("imgsize_show", ar=current, p=CMD_PREFIX))
        return
    ar = _parse_aspect_ratio(arg)
    if not ar:
        await event.edit(t("imgsize_invalid", a=arg))
        return
    config["image_aspect_ratio"] = ar
    save_config()
    await event.edit(t("imgsize_set", ar=ar))


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
    # Same `--ar` / `--<alias>` override mechanism as `.img`
    ar_override, prompt = _extract_ar_flag(prompt.strip())
    if not prompt:
        await event.edit(t("imgedit_usage", p=CMD_PREFIX))
        return
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
    edited_bytes, err = await _edit_image(img_bytes, prompt, aspect_ratio=ar_override)
    if not edited_bytes:
        en, fa = _friendly_image_error(err or "")
        await msg.edit(fa if config.get("bot_lang", "en") == "fa" else en)
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
    except Exception as e:  # noqa: BLE001
        log.error(f"Send edited image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
        return
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass


# ═════════ Combine two images (.mix / .combine / .merge) ═════════
def _msg_has_image(m) -> bool:
    """True if message `m` carries a photo or an image document."""
    if m is None:
        return False
    if getattr(m, "photo", None):
        return True
    doc = getattr(m, "document", None)
    if doc and (getattr(doc, "mime_type", "") or "").startswith("image/"):
        return True
    return False


async def _gather_mix_images(event) -> tuple[list[bytes], str | None]:
    """Collect up to 2 images for `.mix`: from a replied album, a replied single
    image, and/or the command message's own attached image. Returns (images, err)."""
    images: list[bytes] = []
    try:
        if event.is_reply:
            replied = await event.get_reply_message()
            if replied:
                grp = getattr(replied, "grouped_id", None)
                if grp:
                    lo = max(1, replied.id - 9)
                    window = await client.get_messages(
                        event.chat_id, ids=list(range(lo, replied.id + 10)))
                    album = sorted(
                        [m for m in window
                         if m and getattr(m, "grouped_id", None) == grp and _msg_has_image(m)],
                        key=lambda m: m.id)
                    for m in album:
                        if len(images) >= 2:
                            break
                        b = await client.download_media(m, file=bytes)
                        if isinstance(b, bytes) and b:
                            images.append(b)
                elif _msg_has_image(replied):
                    b = await client.download_media(replied, file=bytes)
                    if isinstance(b, bytes) and b:
                        images.append(b)
        if len(images) < 2 and _msg_has_image(event.message):
            b = await client.download_media(event.message, file=bytes)
            if isinstance(b, bytes) and b:
                images.append(b)
    except Exception as e:  # noqa: BLE001
        return [], t("imgedit_dl_error", e=str(e))
    return images, None


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(?:mix|combine|merge)(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_mix(event):
    """Combine two images into one. Optional prompt guides the composition."""
    ready, err = _ai_ready()
    if not ready:
        await event.edit(t("ai_not_ready", err=err))
        return
    raw = (event.pattern_match.group(1) or "").strip()
    ar_override, prompt = _extract_ar_flag(raw) if raw else (None, "")
    prompt = prompt.strip()

    images, gather_err = await _gather_mix_images(event)
    if gather_err:
        await event.edit(gather_err)
        return
    if len(images) < 2:
        await event.edit(t("mix_need_two", p=CMD_PREFIX))
        return
    images = images[:2]

    msg = await event.edit(t("mix_processing"))
    if prompt:
        instruction = (f"Using the provided reference images, {prompt}. "
                       "Produce a single combined image.")
    else:
        instruction = ("Seamlessly combine and blend the provided images into a single "
                       "cohesive image. Merge their subjects and scenes naturally with "
                       "consistent lighting, perspective, color and art style.")
    images_b64 = [base64.b64encode(b).decode("utf-8") for b in images]
    out, gerr = await _combine_images(images_b64, instruction, aspect_ratio=ar_override)
    if not out:
        en, fa = _friendly_image_error(gerr or "")
        await msg.edit(fa if config.get("bot_lang", "en") == "fa" else en)
        return
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(out)
            tmp = f.name
        caption = t("mix_caption", p=prompt[:900]) if prompt else t("mix_caption_default")
        await client.send_file(
            event.chat_id, tmp,
            caption=caption,
            reply_to=event.reply_to_msg_id,
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Send mixed image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
        return
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass
    log.info(f"[.mix] combined {len(images)} images (prompt={'yes' if prompt else 'no'})")


async def _do_image_transform(event, edit_prompt: str, processing_label: str,
                               caption_label: str) -> None:
    """Shared flow for `.style` / `.aged` / `.cartoon`: pull replied image,
    edit with Nano Banana, send back as reply. `edit_prompt` is the final
    instruction sent to Gemini; the two `*_label` strings are user-facing."""
    if not event.is_reply:
        await event.edit(t("imgedit_need_reply"))
        return
    msg = await event.edit(processing_label)
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
    edited_bytes, err = await _edit_image(img_bytes, edit_prompt)
    if not edited_bytes:
        en, fa = _friendly_image_error(err or "")
        await msg.edit(fa if config.get("bot_lang", "en") == "fa" else en)
        return
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(edited_bytes)
            tmp = f.name
        await client.send_file(
            event.chat_id, tmp,
            caption=caption_label,
            reply_to=replied.id,
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"Send transformed image: {e}")
        await msg.edit(t("img_send_failed", e=str(e)))
        return
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass


# ═════════ Image transformations (.style / .aged / .cartoon) ═════════
# Curated style presets. Each maps to a precise English description that the
# image model understands well. Persian names are aliases that resolve via
# `STYLE_ALIAS_FA` so users can type either language.
STYLE_PRESETS: dict[str, str] = {
    "vangogh":    "Van Gogh post-impressionist oil painting with thick swirling brushstrokes and vibrant yellows and blues",
    "monet":      "Claude Monet impressionist oil painting with soft pastels and visible brush strokes",
    "picasso":    "Pablo Picasso cubist style with geometric fragmentation and bold flat colors",
    "anime":      "high-quality Japanese anime art, vibrant colors, expressive features, cel-shaded",
    "ghibli":     "Studio Ghibli anime art style, soft watercolor backgrounds, gentle palette, hand-painted feel",
    "pixar":      "Pixar 3D animation style, smooth surfaces, expressive features, vibrant cinematic lighting",
    "disney":     "classic Disney 2D animation style, expressive characters, vivid colors, hand-drawn feel",
    "watercolor": "delicate watercolor painting with soft washes and bleeding pigments on textured paper",
    "oil":        "classical oil painting with rich textures, dramatic chiaroscuro lighting and visible brush strokes",
    "sketch":     "detailed graphite pencil sketch with cross-hatching and shading on white paper",
    "cyberpunk":  "neon-lit cyberpunk style, retrowave colors, futuristic dystopian city background, rain and fog",
    "comic":      "American comic book style with bold ink outlines, halftone shading and saturated colors",
    "popart":     "Andy Warhol pop art style, bold flat colors, screenprint texture",
    "lego":       "LEGO brick art, plastic block textures, studs visible",
    "minecraft":  "Minecraft blocky voxel style, low-resolution pixelated cubes",
    "pixel":      "16-bit pixel art style with limited palette",
    "vaporwave":  "vaporwave aesthetic, pastel purples and pinks, retro 80s grids and statues",
    "ukiyoe":     "traditional Japanese ukiyo-e woodblock print with flat colors and bold outlines",
    "noir":       "1940s film noir black-and-white photography with dramatic shadows and high contrast",
    "claymation": "claymation stop-motion style, visible fingerprints on clay, soft lighting",
}

STYLE_ALIAS_FA: dict[str, str] = {
    "ون‌گوگ": "vangogh", "ونگوگ": "vangogh", "ون گوگ": "vangogh",
    "مونه": "monet",
    "پیکاسو": "picasso",
    "انیمه": "anime", "انیمیشن": "anime",
    "گیبلی": "ghibli", "جیبلی": "ghibli",
    "پیکسار": "pixar",
    "دیزنی": "disney",
    "آبرنگ": "watercolor", "آبرنگی": "watercolor",
    "رنگ‌روغن": "oil", "رنگ روغن": "oil",
    "اسکچ": "sketch", "طراحی": "sketch", "مدادی": "sketch",
    "سایبرپانک": "cyberpunk", "سایبر پانک": "cyberpunk",
    "کمیک": "comic", "کمیکی": "comic",
    "پاپ‌آرت": "popart", "پاپ آرت": "popart",
    "لگو": "lego", "لگویی": "lego",
    "ماینکرفت": "minecraft", "ماینکرافت": "minecraft",
    "پیکسلی": "pixel", "پیکسل": "pixel",
    "ویپرویو": "vaporwave",
    "ژاپنی": "ukiyoe", "اوکیو": "ukiyoe",
    "نوآر": "noir", "سیاه‌سفید": "noir", "سیاه و سفید": "noir",
    "خمیری": "claymation", "خمیر بازی": "claymation",
}


def _resolve_style(s: str) -> tuple[str | None, str | None]:
    """Return (preset_key, prompt_description). If `s` isn't a known preset,
    treats it as a free-form style description (returns (None, s.strip()))."""
    if not s:
        return None, None
    key = s.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    # Persian alias → english key (try the raw stripped value too)
    persian = STYLE_ALIAS_FA.get(s.strip()) or STYLE_ALIAS_FA.get(s.strip().lower())
    if persian:
        return persian, STYLE_PRESETS[persian]
    if key in STYLE_PRESETS:
        return key, STYLE_PRESETS[key]
    # Free-form: just use the user's text as the style description
    return None, s.strip()


def _parse_age_delta(s: str) -> int | None:
    """Parse `+20`, `-10`, `20y`, `-5 years`, `۲۰` (Persian digits) → signed int.
    Returns None on garbage. Capped at ±80 to keep prompts realistic."""
    if not s:
        return None
    # Convert Persian/Arabic digits to ASCII
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    s = s.strip().translate(trans)
    m = re.match(r"^\s*([+\-]?)\s*(\d{1,3})\s*(?:y|yrs|years|سال)?\s*$", s, re.I)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    n = int(m.group(2))
    if n == 0 or n > 80:
        return None
    return sign * n


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}style(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_style(event):
    arg = event.pattern_match.group(1)
    if not arg or not arg.strip():
        await event.edit(t("style_usage", p=CMD_PREFIX))
        return
    key, description = _resolve_style(arg.strip())
    label_for_user = key or arg.strip()
    prompt = (
        f"Restyle this image as: {description}. "
        f"Preserve the main subject's identity, pose, and overall composition. "
        f"Only change the artistic style — no extra elements added or removed."
    )
    await _do_image_transform(
        event,
        edit_prompt=prompt,
        processing_label=t("style_processing", s=label_for_user),
        caption_label=t("style_caption", s=label_for_user),
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}aged?(?:\s+(\S+))?$"))
@owner_only
async def cmd_aged(event):
    arg = event.pattern_match.group(1)
    delta = _parse_age_delta(arg) if arg else None
    if delta is None:
        await event.edit(t("aged_usage", p=CMD_PREFIX))
        return
    direction = "older" if delta > 0 else "younger"
    years = abs(delta)
    prompt = (
        f"Make the person in this photo look exactly {years} years {direction}. "
        f"Preserve their identity, gender, ethnicity, hairstyle (adjust only for natural aging), "
        f"facial features, clothing and the background scene. "
        f"Photorealistic result, same lighting, same camera angle."
    )
    label = f"{'+' if delta > 0 else '-'}{years}"
    await _do_image_transform(
        event,
        edit_prompt=prompt,
        processing_label=t("aged_processing", y=label),
        caption_label=t("aged_caption", y=label),
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}cartoon(?:\s+(\S+))?$"))
@owner_only
async def cmd_cartoon(event):
    arg = (event.pattern_match.group(1) or "pixar").strip()
    # Cartoon defaults to pixar but accepts any of: pixar/disney/anime/ghibli
    key, description = _resolve_style(arg)
    if not key or key not in {"pixar", "disney", "anime", "ghibli"}:
        # Force a sensible default if user passed something exotic
        key, description = "pixar", STYLE_PRESETS["pixar"]
    prompt = (
        f"Transform this photo into {description}. "
        f"Keep the subject's identity recognizable through cartoon features. "
        f"Maintain the original pose, composition, and background context but in the new style."
    )
    await _do_image_transform(
        event,
        edit_prompt=prompt,
        processing_label=t("cartoon_processing", s=key),
        caption_label=t("cartoon_caption", s=key),
    )


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


# ═════════ Text-to-Speech (.say / .voice) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}say(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_say(event):
    """Convert text to a natural voice message. `.say <text>` or reply + `.say`."""
    ready, err = _tts_ready()
    if not ready:
        await event.edit(t("say_not_ready", err=err))
        return
    arg = (event.pattern_match.group(1) or "").strip()
    voice_override, arg = _extract_voice_flag(arg) if arg else (None, "")

    text = arg
    replied = None
    if not text and event.is_reply:
        try:
            replied = await event.get_reply_message()
            text = ((replied.raw_text or replied.text or "") if replied else "").strip()
        except Exception as e:  # noqa: BLE001
            await event.edit(t("say_reply_error", e=str(e)))
            return
    if not text:
        await event.edit(t("say_usage", p=CMD_PREFIX,
                           v=config.get("tts_voice", "nova"),
                           m=config.get("tts_model", "tts-1-hd")))
        return

    voice = voice_override or config.get("tts_voice", "nova")
    model = config.get("tts_model", "tts-1-hd")
    msg = await event.edit(t("say_processing", v=voice))

    reply_to = (replied.id if replied else event.reply_to_msg_id)
    chunks = _chunk_text(text, 4000)
    sent_any = False
    for chunk in chunks:
        audio, gerr = await _tts_generate(chunk, voice, model, "opus")
        if not audio:
            en, fa = _friendly_tts_error(gerr or "")
            await msg.edit(fa if config.get("bot_lang", "en") == "fa" else en)
            return
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(audio)
                tmp = f.name
            await client.send_file(
                event.chat_id, tmp,
                voice_note=True,
                attributes=[DocumentAttributeAudio(duration=_opus_duration(audio), voice=True)],
                reply_to=reply_to,
            )
            sent_any = True
        except Exception as e:  # noqa: BLE001
            log.error(f"[.say] send failed: {e}")
            await msg.edit(t("say_send_failed", e=str(e)))
            return
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    if sent_any:
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
    log.info(f"[.say] sent {len(chunks)} voice msg(s) voice={voice} model={model}")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}voice(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_voice(event):
    """View/set the default TTS voice and model."""
    arg = (event.pattern_match.group(1) or "").strip()
    if not arg:
        await event.edit(t("voice_show",
                           v=config.get("tts_voice", "nova"),
                           m=config.get("tts_model", "tts-1-hd"),
                           p=CMD_PREFIX))
        return
    parts = arg.split()
    if parts[0].lower() == "model":
        if len(parts) < 2 or parts[1].lower() not in TTS_MODELS:
            await event.edit(t("voice_model_invalid", p=CMD_PREFIX))
            return
        config["tts_model"] = parts[1].lower()
        save_config()
        await event.edit(t("voice_model_set", m=config["tts_model"]))
        return
    v = parts[0].lower()
    if v not in TTS_VOICES:
        await event.edit(t("voice_invalid", p=CMD_PREFIX))
        return
    config["tts_voice"] = v
    save_config()
    await event.edit(t("voice_set", v=v))


# ═════════ URL Uploader (.up) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}up(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_upload(event):
    """Download a file from a direct URL and upload it to the current chat."""
    arg = (event.pattern_match.group(1) or "").strip()
    urls = _extract_urls(arg)
    replied = None
    if not urls and event.is_reply:
        try:
            replied = await event.get_reply_message()
            if replied and (replied.raw_text or ""):
                urls = _extract_urls(replied.raw_text)
        except Exception:  # noqa: BLE001
            replied = None
    if not urls:
        if not arg and not event.is_reply:
            await event.edit(t("up_usage", p=CMD_PREFIX))
        else:
            await event.edit(t("up_no_url"))
        return

    url = urls[0]
    reply_to = (replied.id if replied else event.reply_to_msg_id)
    status = await event.edit(t("up_starting", u=url[:100]))
    tmpdir = tempfile.mkdtemp(prefix="bidar_up_")
    try:
        info, derr = await _download_url_file(url, tmpdir, status)
        if not info:
            await _safe_edit(status, derr or t("up_failed", e="download failed"))
            return

        category = _categorize_upload(info["name"], info["mime"])
        await _safe_edit(status, t("up_uploading", name=info["name"][:60]))
        caption = _build_upload_caption(info, category)

        last_up = [0.0]

        def up_prog(sent, total):
            now = time.time()
            if total and now - last_up[0] >= 3:
                last_up[0] = now
                pct = sent * 100 // total
                asyncio.create_task(_safe_edit(status, t(
                    "up_uploading_pct", bar=_progress_bar(pct), pct=pct,
                    done=_human_size(sent), total=_human_size(total))))

        await client.send_file(
            event.chat_id, info["path"],
            caption=caption,
            force_document=(category == "document"),
            supports_streaming=(category == "video"),
            reply_to=reply_to,
            progress_callback=up_prog,
        )
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass
        log.info(f"[.up] uploaded {info['name']} ({_human_size(info['size'])}, {category}) from {url[:80]}")
    except Exception as e:  # noqa: BLE001
        log.error(f"[.up] failed: {e}")
        await _safe_edit(status, t("up_failed", e=str(e)[:200]))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═════════ Document Q&A (.ask / .pdf) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(?:ask|pdf)(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_ask(event):
    """Analyse a PDF/text file and answer questions about it (multi-turn)."""
    raw = (event.pattern_match.group(1) or "").strip()

    if raw.lower() in ("reset", "clear", "forget", "بازنشانی", "پاک", "فراموش"):
        _doc_cache.pop(event.chat_id, None)
        await event.edit(t("ask_cleared"))
        return

    # Detect a supported document on the replied message (the "load" path)
    replied = None
    doc_meta = None
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
        except Exception:  # noqa: BLE001
            replied = None
        if replied:
            f = getattr(replied, "file", None)
            if f and (getattr(f, "name", None) or getattr(f, "mime_type", None)):
                name = getattr(f, "name", None) or "document"
                mime = getattr(f, "mime_type", "") or ""
                size = getattr(f, "size", 0) or 0
                if (mime or "").lower().startswith("image/"):
                    pass  # images belong to .r / .ocr, not .ask
                elif _doc_is_supported(name, mime):
                    doc_meta = (name, mime, size)
                else:
                    await event.edit(t("ask_unsupported"))
                    return

    if doc_meta:
        name, mime, size = doc_meta
        if size and size > MAX_DOC_BYTES:
            await event.edit(t("ask_too_big", size=_human_size(size),
                                max=_human_size(MAX_DOC_BYTES)))
            return
        status = await event.edit(t("ask_analyzing", name=name[:60]))
        try:
            data = await client.download_media(replied, file=bytes)
        except Exception as e:  # noqa: BLE001
            await status.edit(t("ask_dl_error", e=str(e)[:200]))
            return
        if not isinstance(data, bytes) or not data:
            await status.edit(t("ask_dl_error", e="empty file"))
            return

        text, err, truncated = _extract_document_text(data, name, mime)
        if err == "pdf_lib":
            await status.edit(t("ask_pdf_lib"))
            return
        if err == "docx_lib":
            await status.edit(t("ask_docx_lib"))
            return
        if err == "unsupported":
            await status.edit(t("ask_unsupported"))
            return
        if err == "empty":
            await status.edit(t("ask_empty", p=CMD_PREFIX))
            return
        if err:
            await status.edit(t("ask_failed", e=err))
            return

        doc = {"name": name, "text": text, "history": [],
               "truncated": truncated, "ts": time.time()}
        _doc_cache[event.chat_id] = doc
        reply_to = replied.id

        if raw:
            ans, gerr = await _answer_document(doc, raw)
            if not ans:
                await status.edit(t("ask_failed", e=(gerr or "")[:200]))
                return
            doc["history"].append((raw, ans))
            await _reply_long(status, event.chat_id, ans, reply_to)
        else:
            overview, _ = await _answer_document(
                doc, "Give a brief overview: what is this document about, its main "
                     "topics/sections, and key takeaways. Keep it under 8 bullet points.")
            trunc = t("ask_trunc_note") if truncated else ""
            body = t("ask_loaded", name=name, chars=f"{len(text):,}", trunc=trunc,
                     overview=(overview or ""), p=CMD_PREFIX)
            await _reply_long(status, event.chat_id, body, reply_to)
        log.info(f"[.ask] loaded {name} ({len(text)} chars, trunc={truncated}) "
                 f"q={'yes' if raw else 'no'}")
        return

    # No document on reply → follow-up question on the cached document
    cached = _doc_cache.get(event.chat_id)
    if not cached:
        await event.edit(t("ask_no_doc", p=CMD_PREFIX) if (raw or event.is_reply)
                         else t("ask_usage", p=CMD_PREFIX))
        return
    if not raw:
        await event.edit(t("ask_no_question", name=cached["name"], p=CMD_PREFIX))
        return
    status = await event.edit(t("ask_thinking"))
    ans, gerr = await _answer_document(cached, raw)
    if not ans:
        await status.edit(t("ask_failed", e=(gerr or "")[:200]))
        return
    cached["history"].append((raw, ans))
    cached["history"] = cached["history"][-6:]
    await _reply_long(status, event.chat_id, ans, event.reply_to_msg_id)
    log.info(f"[.ask] follow-up on {cached['name']}")


# ═════════ Server status (.server / .sys / .vps) ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(?:server|sys|vps)$"))
@owner_only
async def cmd_server(event):
    """Show a stylish VPS resource-usage card (CPU / RAM / disk / uptime / net)."""
    if not PSUTIL_OK:
        await event.edit(t("server_no_psutil"))
        return
    msg = await event.edit(t("server_gathering"))
    try:
        data = await _gather_server_status()
        await msg.edit(_format_server_status(data, config.get("bot_lang", "en")),
                       link_preview=False)
    except Exception as e:  # noqa: BLE001
        log.error(f"[.server] {e}")
        await msg.edit(t("server_error", e=str(e)[:200]))
    log.info("[.server] status shown")


# ═════════ FreeCAD Stripe checkout link (.fc) ═════════
# Available to the owner anywhere, and to ANY member in whitelisted (Allow) groups.
FC_CHECKOUT_URL = os.environ.get(
    "FC_CHECKOUT_URL", "https://www.freecad.org/stripe-checkout-session.php?amount=1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow, so we can read the Location header."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _fetch_fc_checkout() -> str | None:
    """Hit the FreeCAD endpoint and return the Stripe checkout URL from the
    303 redirect's Location header (without following the redirect)."""
    req = urllib.request.Request(
        FC_CHECKOUT_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(req, timeout=30)
        loc = resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
    if not loc:
        return None
    return loc if loc.startswith("http") else urllib.parse.urljoin(FC_CHECKOUT_URL, loc)


def _fc_can_use(event) -> bool:
    """Owner (anywhere) or any member inside a whitelisted (Allow) group."""
    if _is_owner(event):
        return True
    return bool(not event.is_private and _is_chat_allowed(event.chat_id))


@client.on(events.NewMessage(pattern=rf"^\{CMD_PREFIX}fc$"))
async def cmd_checkout(event):
    """Fetch a Stripe checkout link. Usable by anyone in whitelisted groups."""
    if not _fc_can_use(event):
        return
    status = await event.respond(t("fc_generating"))
    try:
        await event.delete()  # remove the ".fc" command message; keep only the result
    except Exception:  # noqa: BLE001
        pass
    try:
        url = await asyncio.to_thread(_fetch_fc_checkout)
    except Exception as e:  # noqa: BLE001
        log.error(f"[.fc] fetch failed: {e}")
        await status.edit(t("fc_failed", e=str(e)[:200]))
        return
    if not url or "checkout.stripe.com" not in url:
        await status.edit(t("fc_failed", e="no checkout link returned"))
        return
    await status.edit(t("fc_result", url=url), link_preview=False)
    log.info(f"[.fc] checkout link generated by {event.sender_id} in chat {event.chat_id}")


# ═════════ Merge all .txt files of a chat (.mergetxt) ═════════
MAX_MERGE_BYTES = 500 * 1024 * 1024  # 500 MB combined cap


def _normalize_chat_ref(ref: str):
    """Turn a user-supplied chat reference into something get_entity accepts."""
    ref = ref.strip()
    if re.fullmatch(r"-?\d+", ref):
        return int(ref)
    m = re.search(r"(?:t\.me/|telegram\.me/)(\+?[\w]+)", ref, re.I)
    if m:
        return m.group(1)
    return ref.lstrip("@") if ref.startswith("@") else ref


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(?:mergetxt|txtmerge)(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_mergetxt(event):
    """Merge every .txt file of a channel/group into a single .txt file."""
    arg = (event.pattern_match.group(1) or "").strip()
    if arg:
        try:
            target = await client.get_entity(_normalize_chat_ref(arg))
        except Exception as e:  # noqa: BLE001
            await event.edit(t("mtxt_bad_link", e=str(e)[:150]))
            return
    else:
        try:
            target = await event.get_input_chat()
        except Exception as e:  # noqa: BLE001
            await event.edit(t("mtxt_usage", p=CMD_PREFIX))
            return

    status = await event.edit(t("mtxt_scanning"))
    title = getattr(target, "title", None) or getattr(target, "username", None) or "chat"
    tmpdir = tempfile.mkdtemp(prefix="bidar_mtxt_")
    out_path = os.path.join(tmpdir, "merged.txt")
    count = 0
    total = 0
    truncated = False
    last_edit = 0.0
    try:
        with open(out_path, "w", encoding="utf-8") as out:
            out.write(f"# Merged .txt files from: {title}\n"
                      f"# Generated by Bidar on {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            async for msg in client.iter_messages(
                    target, filter=InputMessagesFilterDocument, reverse=True):
                f = getattr(msg, "file", None)
                if not f:
                    continue
                name = f.name or ""
                mime = (f.mime_type or "").lower()
                if not (name.lower().endswith(".txt") or mime == "text/plain"):
                    continue
                try:
                    data = await client.download_media(msg, file=bytes)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(data, bytes) or not data:
                    continue
                count += 1
                out.write(f"\n\n===== FILE {count}: {name or 'untitled.txt'} =====\n")
                out.write(data.decode("utf-8", errors="replace"))
                total += len(data)
                if total > MAX_MERGE_BYTES:
                    truncated = True
                    break
                now = time.time()
                if now - last_edit >= 3:
                    last_edit = now
                    await _safe_edit(status, t("mtxt_progress", n=count,
                                               size=_human_size(total)))
        if count == 0:
            await status.edit(t("mtxt_none"))
            return

        safe_title = re.sub(r'[\\/:*?"<>|]+', "_", str(title)).strip() or "chat"
        final_name = f"{safe_title[:50]}_merged_{count}txt.txt"
        final_path = os.path.join(tmpdir, final_name)
        os.rename(out_path, final_path)

        await _safe_edit(status, t("mtxt_uploading", n=count))
        size_str = _human_size(total) + ("+" if truncated else "")
        await client.send_file(
            event.chat_id, final_path,
            caption=t("mtxt_caption", title=title, n=count, size=size_str),
            force_document=True,
            reply_to=event.reply_to_msg_id,
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"[.mergetxt] failed: {e}")
        await _safe_edit(status, t("mtxt_failed", e=str(e)[:200]))
        return
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    try:
        await status.delete()
    except Exception:  # noqa: BLE001
        pass
    log.info(f"[.mergetxt] merged {count} txt files from {title} ({_human_size(total)})")


# ═════════ Split a large file into size-limited parts (.split) ═════════
MAX_PART_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB per part (Telegram non-premium limit)
MIN_PART_SIZE = 1024                    # 1 KB


def _parse_size_arg(s: str):
    """Parse '100mb' / '1gb' / '250kb' / '500' → bytes (bare number = MB). None if invalid."""
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|k|m|g)?\s*", s, re.I)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "mb").lower()
    mult = {"b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2,
            "g": 1024**3, "gb": 1024**3}[unit]
    n = int(num * mult)
    if n < MIN_PART_SIZE or n > MAX_PART_SIZE:
        return None
    return n


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}split(?:\s+(\S+))?$"))
@owner_only
async def cmd_split(event):
    """Split a replied file into line-aligned parts of a chosen max size."""
    if not event.is_reply:
        await event.edit(t("split_no_file", p=CMD_PREFIX))
        return
    replied = await event.get_reply_message()
    f = getattr(replied, "file", None) if replied else None
    if not f:
        await event.edit(t("split_no_file", p=CMD_PREFIX))
        return

    part_bytes = _parse_size_arg(event.pattern_match.group(1))
    if not part_bytes:
        await event.edit(t("split_bad_size", max=_human_size(MAX_PART_SIZE)))
        return

    orig_name = f.name or "file.txt"
    base, ext = os.path.splitext(orig_name)
    base = re.sub(r'[\\/:*?"<>|]+', "_", base).strip() or "file"
    ext = ext or ".txt"

    status = await event.edit(t("split_downloading"))
    tmpdir = tempfile.mkdtemp(prefix="bidar_split_")
    src_path = os.path.join(tmpdir, "source" + ext)
    total_bytes = getattr(f, "size", 0) or 0
    reply_to = replied.id

    last_edit = [0.0]

    async def _dl_cb(recv, total):
        now = time.time()
        if now - last_edit[0] >= 3:
            last_edit[0] = now
            pct = (recv * 100 // total) if total else 0
            await _safe_edit(status, t("split_downloading_pct", pct=pct,
                                       done=_human_size(recv),
                                       total=_human_size(total or total_bytes)))

    try:
        await client.download_media(replied, file=src_path, progress_callback=_dl_cb)

        part_no = 0
        cur_size = 0
        cur_path = None
        cur_fh = None
        parts = []  # (path, size)
        last_edit[0] = 0.0

        def _open_part():
            nonlocal part_no, cur_path, cur_fh, cur_size
            part_no += 1
            cur_path = os.path.join(tmpdir, f"{base[:50]}_part{part_no}{ext}")
            cur_fh = open(cur_path, "wb")
            cur_size = 0

        with open(src_path, "rb") as src:
            for line in src:  # iterates line-by-line, keeps line endings
                if cur_fh is None:
                    _open_part()
                # roll to next part if this line would overflow (and part not empty)
                if cur_size and cur_size + len(line) > part_bytes:
                    cur_fh.close()
                    parts.append((cur_path, cur_size))
                    _open_part()
                cur_fh.write(line)
                cur_size += len(line)
                now = time.time()
                if now - last_edit[0] >= 3:
                    last_edit[0] = now
                    await _safe_edit(status, t("split_splitting",
                                               size=_human_size(part_bytes), n=part_no))
            if cur_fh is not None:
                cur_fh.close()
                if cur_size > 0:
                    parts.append((cur_path, cur_size))
                else:
                    try:
                        os.remove(cur_path)
                    except OSError:
                        pass

        if not parts:
            await _safe_edit(status, t("split_failed", e="file is empty"))
            return

        total_parts = len(parts)
        sent_total = 0
        for idx, (ppath, psize) in enumerate(parts, 1):
            await _safe_edit(status, t("split_uploading", n=idx, size=_human_size(psize)))
            await client.send_file(
                event.chat_id, ppath,
                caption=t("split_caption", name=orig_name, n=idx,
                          total=total_parts, size=_human_size(psize)),
                force_document=True,
                reply_to=reply_to,
            )
            sent_total += psize
            try:
                os.remove(ppath)
            except OSError:
                pass

        await _safe_edit(status, t("split_done", n=total_parts,
                                   size=_human_size(sent_total)))
    except Exception as e:  # noqa: BLE001
        log.error(f"[.split] failed: {e}")
        await _safe_edit(status, t("split_failed", e=str(e)[:200]))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═════════ Text → file (.file / .mkfile) ═════════
def _build_filename(token: str) -> str:
    """Turn a user token into a safe filename.
    'py' → 'file.py' · '.json' → 'file.json' · 'notes.md' → 'notes.md'."""
    token = token.strip().strip('"').strip("'")
    if "." in token.lstrip("."):
        name = token
    else:
        ext = re.sub(r"[^A-Za-z0-9]", "", token.lstrip("."))[:12] or "txt"
        name = f"file.{ext}"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip().strip(".")
    if not name:
        name = "file.txt"
    if "." not in name:
        name += ".txt"
    return name[:120]


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}(?:file|mkfile|tofile)(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_mkfile(event):
    """Create a file from text (or a replied message) with a chosen extension."""
    arg = (event.pattern_match.group(1) or "").strip()
    if not arg:
        await event.edit(t("file_usage", p=CMD_PREFIX))
        return
    parts = arg.split(None, 1)
    token = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""

    content = rest
    replied = None
    if event.is_reply and not content:
        try:
            replied = await event.get_reply_message()
        except Exception:  # noqa: BLE001
            replied = None
        if replied:
            content = replied.raw_text or replied.text or ""
    if not content:
        await event.edit(t("file_no_text", p=CMD_PREFIX))
        return

    filename = _build_filename(token)
    data = content.encode("utf-8")
    reply_to = (replied.id if replied else event.reply_to_msg_id)
    status = await event.edit(t("file_creating", name=filename))
    tmpdir = tempfile.mkdtemp(prefix="bidar_mk_")
    try:
        path = os.path.join(tmpdir, filename)
        with open(path, "wb") as f:
            f.write(data)
        await client.send_file(
            event.chat_id, path,
            caption=t("file_caption", name=filename, size=_human_size(len(data))),
            force_document=True,
            reply_to=reply_to,
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"[.file] failed: {e}")
        await status.edit(t("file_failed", e=str(e)[:200]))
        return
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    try:
        await status.delete()
    except Exception:  # noqa: BLE001
        pass
    log.info(f"[.file] created {filename} ({len(data)} bytes)")


# ═════════ TL;DR — Link summariser ═════════
@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}tldr(?:\s+([\s\S]+))?$"))
@owner_only
async def cmd_tldr(event):
    """Summarise URL(s) — either from the command argument or from a replied message."""
    arg = (event.pattern_match.group(1) or "").strip()
    sources_text = arg
    replied = None
    # If no inline URL, fall back to replied message
    if not _extract_urls(sources_text):
        if event.is_reply:
            try:
                replied = await event.get_reply_message()
            except Exception:  # noqa: BLE001
                replied = None
            if replied and (replied.raw_text or ""):
                sources_text = replied.raw_text

    urls = _extract_urls(sources_text)
    if not urls:
        # Show usage when called with nothing at all; otherwise an explicit message
        if not arg and not event.is_reply:
            await event.edit(t("tldr_usage", p=CMD_PREFIX))
        else:
            await event.edit(t("tldr_no_url"))
        return

    # User explicitly requested .tldr always summarise in Persian, regardless of bot_lang.
    lang = "fa"
    if len(urls) == 1:
        status = await event.edit(t("tldr_processing_one", u=urls[0][:120]))
    else:
        status = await event.edit(t("tldr_processing_multi", n=len(urls)))

    parts = await asyncio.gather(*[_tldr_one(u, lang) for u in urls],
                                 return_exceptions=True)
    chunks: list[str] = []
    for u, p in zip(urls, parts):
        if isinstance(p, Exception):
            log.error(f"[.tldr] failed for {u}: {p}")
            chunks.append(f"❌ `{u[:80]}` — `{str(p)[:200]}`")
        else:
            chunks.append(p)

    full = t("tldr_separator").join(chunks)
    reply_to = (replied.id if replied else event.reply_to_msg_id)
    # Telegram limit is ~4096; trim with link to source if too long
    if len(full) <= 3900:
        try:
            await status.edit(full, link_preview=False)
        except Exception:  # noqa: BLE001
            # Fallback: delete status, send fresh (handles cases where
            # the message can't be edited because of formatting size)
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
            await client.send_message(event.chat_id, full,
                                      link_preview=False,
                                      reply_to=reply_to)
    else:
        # Edit status with first chunk, send the rest as replies to keep the thread tidy
        first = full[:3900] + "\n\n…"
        await status.edit(first, link_preview=False)
        rest = full[3900:]
        while rest:
            piece = rest[:3900]
            rest = rest[3900:]
            await client.send_message(event.chat_id, piece,
                                      link_preview=False,
                                      reply_to=reply_to)
    log.info(f"[.tldr] summarised {len(urls)} URL(s)")


# ═════════ Chat summariser (.sum) ═════════
async def _fetch_chat_messages(event, limit: int) -> tuple[list[str], int]:
    """Pull up to `limit` recent messages (newest → oldest) and format them as
    'Name: text' lines. Skips empty/service messages and the user's own commands.
    Returns (lines_oldest_to_newest, actual_count).
    """
    me = await client.get_me()
    own_id = me.id
    lines: list[str] = []
    name_cache: dict[int, str] = {}
    try:
        async for msg in client.iter_messages(event.chat_id, limit=limit + 20):
            text = (msg.raw_text or "").strip()
            if not text:
                # Mark media-only msgs with a tiny placeholder so the AI has context
                if msg.photo:
                    text = "[photo]"
                elif msg.video or msg.video_note:
                    text = "[video]"
                elif msg.voice:
                    text = "[voice note]"
                elif msg.sticker:
                    text = "[sticker]"
                elif msg.document:
                    text = "[file]"
                else:
                    continue
            # Skip the owner's own bot commands
            if msg.sender_id == own_id and text.startswith(CMD_PREFIX):
                continue
            # Resolve sender display name (cached)
            sid = msg.sender_id or 0
            name = name_cache.get(sid)
            if name is None:
                if sid == own_id:
                    name = "Me"
                else:
                    try:
                        s = await msg.get_sender()
                        if s is None:
                            name = "Unknown"
                        elif getattr(s, "first_name", None):
                            name = s.first_name
                            if getattr(s, "last_name", None):
                                name = f"{name} {s.last_name}"
                        elif getattr(s, "title", None):
                            name = s.title
                        elif getattr(s, "username", None):
                            name = f"@{s.username}"
                        else:
                            name = "Unknown"
                    except Exception:  # noqa: BLE001
                        name = "Unknown"
                name_cache[sid] = name[:30]
            # Trim very long messages so we fit in the AI context window
            if len(text) > 500:
                text = text[:500] + "…"
            lines.append(f"{name_cache[sid]}: {text}")
            if len(lines) >= limit:
                break
    except Exception as e:  # noqa: BLE001
        log.error(f"[.sum] iter_messages failed: {e}")
        raise
    lines.reverse()  # chronological order
    return lines, len(lines)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{CMD_PREFIX}sum(?:\s+(\d+))?$"))
@owner_only
async def cmd_summary(event):
    arg = event.pattern_match.group(1)
    if arg is None:
        n = 50
    else:
        n = max(5, min(200, int(arg)))
    status = await event.edit(t("sum_reading", n=n))
    try:
        lines, count = await _fetch_chat_messages(event, n)
    except Exception as e:  # noqa: BLE001
        await status.edit(t("sum_failed", e=str(e)[:200]))
        return
    if not lines:
        await status.edit(t("sum_no_msgs"))
        return

    # Pack a compact transcript for Gemini. Hard cap so we always stay safely
    # below the context window (≈8KB body keeps fast models snappy).
    transcript = "\n".join(lines)[-7500:]
    prompt = (
        "Summarise the following Telegram chat transcript in **Persian (Farsi)**. "
        "Format with these sections (use bold headers):\n"
        "**🎯 موضوعات اصلی** — 3-5 bullets covering the main topics discussed\n"
        "**💡 نکات کلیدی** — 3-5 bullets with key facts, opinions or insights shared\n"
        "**❓ سؤالات/پیشنهادات بدون پاسخ** — only if any exist\n"
        "**✅ تصمیمات/اقدامات** — only if any decisions were made or actions agreed on\n\n"
        "Rules:\n"
        "• No preamble, no 'Here is the summary', no closing remarks.\n"
        "• Be concise — one line per bullet, bold key terms with **double asterisks**.\n"
        "• If the chat is mostly small talk or off-topic banter, just give 3-4 bullets describing the vibe.\n"
        "• Skip empty sections entirely (no 'N/A').\n\n"
        f"=== TRANSCRIPT ({count} messages, oldest → newest) ===\n{transcript}"
    )
    summary = await _ai_summarise(prompt)
    if not summary:
        await status.edit(t("sum_failed", e="AI returned nothing"))
        return
    out = t("sum_header", n=count, s=summary)
    if len(out) <= 3900:
        await status.edit(out, link_preview=False)
    else:
        await status.edit(out[:3900] + "\n\n…", link_preview=False)
        rest = out[3900:]
        while rest:
            piece, rest = rest[:3900], rest[3900:]
            await client.send_message(event.chat_id, piece, link_preview=False)
    log.info(f"[.sum] summarised {count} messages in chat {event.chat_id}")


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
        # Pass remaining results as fallbacks so that DRM-protected picks
        # (SoundCloud Go+ / paid tracks) automatically roll over to the
        # next available result instead of dead-ending the user.
        primary = results[idx - 1]["url"]
        fallbacks = [r["url"] for i, r in enumerate(results, 1) if i != idx]
        await _music_download_and_send(
            event, primary, "soundcloud", False,
            fallback_urls=fallbacks,
        )
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
        f"🎨 Image: `{config.get('image_model','-')}`  📐 `{config.get('image_aspect_ratio','1:1')}`\n"
        f"🔊 Voice: `{config.get('tts_voice','nova')}`  📚 `{config.get('tts_model','tts-1-hd')}`\n"
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
_BOT_MSG_PREFIXES = (
    "🎵", "🔎", "📤", "❌", "✅", "⚠️", "ℹ️", "📋",
    # Captions / fresh messages sent by other features (search, image tools,
    # tldr, sum, ocr, uploader) — may themselves contain music URLs and must be ignored.
    "🔍", "🔒", "🎨", "🖼", "👴", "🧒", "📰", "🌐", "📦", "▶️", "📊", "📖",
    "📥", "🎬", "📄", "🎭", "🖥", "📚",
)


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

    if shutil.which("ffmpeg") is None:
        log.warning("⚠️ ffmpeg not found — music downloads may fail or skip MP3 "
                    "conversion. Install it: sudo apt install -y ffmpeg")

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
