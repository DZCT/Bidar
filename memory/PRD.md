# PRD — Bidar v1.7.0 (Always Online Telegram Userbot + AI Assistant)

## Problem Statement
یوزربات تلگرام همیشه آنلاین با قابلیت پاسخ خودکار هوشمند (GPT/Claude/Gemini از طریق Emergent Universal Key) که در چت خصوصی و گروه‌ها هم بتونه با context کار کنه + ابزارهای جانبی AI (ترجمه، تولید/ویرایش تصویر، OCR، جستجوی جهانی، رابط دوزبانه).

## User Context
- یوزرنیم گیت‌هاب: `MamawliV2`
- ریپو: `MamawliV2/Bidar` (Private، با PAT)
- محل اجرا: VPS (Ubuntu 22.04.1)
- زبان ترجیحی کاربر: فارسی

## Tech Stack
- **Backend**: Python 3.10+, Telethon (Asyncio)
- **AI**: `emergentintegrations` library
  - Gemini 3 Flash (Text) — auto-reply + manual reply
  - Gemini Nano Banana (Image gen/edit + OCR)
- **Storage**: JSON persistent (`bidar_config.json`) + Telethon session file
- **Deployment**: systemd service via one-line `install.sh` (private repo with PAT)

## Feature Matrix (v1.7.0)

### v1.0.x — Foundation (Completed)
- ✅ Persistent online via `UpdateStatusRequest` periodic
- ✅ Owner-only command lock (double safety: `outgoing=True` + `@owner_only`)
- ✅ Static auto-reply with per-chat cooldown
- ✅ Persistent JSON config

### v1.3.0 — AI Assistant (Completed)
- ✅ `emergentintegrations.llm.chat` with Emergent Universal Key
- ✅ Default model: `gemini-3-flash-preview`
- ✅ Per-chat session context (`private_{user_id}` / `group_{chat_id}`)
- ✅ Group AI replies on mention/reply only
- ✅ Customizable persona
- ✅ Cooldown protection in groups

### v1.4.0 — Translation (Completed)
- ✅ `.lang <code>` — default target language
- ✅ `.tl <text>` — translate to default (or reply target)
- ✅ `.to <code> <text>` — translate + edit your own message

### v1.5.0 — Image (Completed)
- ✅ `.img <description>` — generate via Nano Banana
- ✅ `.imgedit <change>` — edit image (reply to image)
- ✅ `.imgmodel <model>` — switch image model
- ✅ `.r [hint]` — manual AI reply generator
- ✅ `.ocr` — OCR via Gemini Vision

### v1.6.0 — Bilingual UI (Completed)
- ✅ Full i18n dictionary (en + fa)
- ✅ `t(key, **kwargs)` helper for all system messages
- ✅ `.botlang <en|fa>` — switch UI language at runtime

### v1.7.0 — Global Search (Completed Feb 2026)
- ✅ `.search <query>` — searches ALL **normal** chats (private + groups + non-restricted channels)
- ✅ `.searchall <query>` — searches **only** restricted/blocked channels
- ✅ Output: human-readable `.txt` file with chat name, ID, date, msg ID, sender, message body
- ✅ Sorted by match-count (most-relevant chat first)
- ✅ Progress updates every 500 chats (avoid Telegram edit rate-limit)
- ✅ FloodWait handling per-chat
- ✅ Min query length 3 chars
- ✅ Bilingual UI keys + help menu entries
- ✅ Unit test: `tests/test_search.py` — 6 tests, all passing

## Commands Summary (v1.7.0)
**Total: 30+ commands**, all `@owner_only`

| Category | Commands |
|---|---|
| Online | `.online`, `.interval` |
| Auto-reply | `.reply`, `.setmsg`, `.afk` |
| AI | `.ai`, `.aigroups`, `.personality`, `.aimodel`, `.aireset`, `.groupcd`, `.r` |
| Translation | `.lang`, `.tl`, `.to` |
| Image | `.img`, `.imgedit`, `.imgmodel`, `.ocr` |
| Search | `.search`, `.searchall` |
| Admin | `.botlang`, `.restart` |
| Info | `.ping`, `.stats`, `.alive`, `.id`, `.help` |

## Architecture
```
/app/bidar/
├── bidar.py              # ~1730 lines (all logic + i18n dict)
├── tests/
│   └── test_search.py    # Unit tests for search feature
├── install.sh            # One-line install (PAT-based)
├── update.sh             # Safe update script
├── bidar.service         # systemd template
├── requirements.txt
├── .env.example
├── README.md
└── LICENSE
```

## Critical Notes for Future Agents
1. **i18n is MANDATORY**: any new system message MUST be added to `I18N` dict (both `en` and `fa`) and accessed via `t("key", **kwargs)`.
2. **Don't block the terminal**: never run `python bidar.py` in foreground — use unit tests in `/app/bidar/tests/` or syntax/lint checks.
3. **Telegram rate limits**: edit/send operations have rate limits. Always batch progress updates (current threshold: every 500 chats).
4. **Owner-only**: every command handler must use `@owner_only`. Double safety: `outgoing=True` in event filter + `sender_id == OWNER_ID` check.
5. **Emergent Universal Key**: provided via `EMERGENT_LLM_KEY` env var. Don't hardcode.

## Install Command (Private Repo with PAT)
```bash
export GH_TOKEN="github_pat_..."
bash <(curl -fsSL -H "Authorization: token $GH_TOKEN" \
  https://raw.githubusercontent.com/MamawliV2/Bidar/main/bidar/install.sh)
```

## Test Results (Feb 13, 2026)
✅ Syntax check passes (`python -c "import ast; ast.parse(...)"`)
✅ Lint check passes (`ruff`)
✅ Unit tests for `.search` / `.searchall`:
   - Normal mode skips restricted + bots
   - Restricted-only mode picks ONLY restricted dialogs
   - Report formatting correct for both modes
   - All 9 i18n search keys present (en + fa)
   - Progress callback fires exactly every 500 chats

## Next Action Items
- کاربر "Save to GitHub" بزنه تا v1.7.0 روی ریپو push بشه
- روی VPS با `bash update.sh` آپدیت کنه
- توی تلگرام `.help` رو ببینه و `.search` / `.searchall` رو تست کنه

## Backlog (Prioritized)
### P1
- 🌙 Night mode (AFK/offline خودکار شبانه)
- 🎙 Voice-to-Text با Whisper (روی reply به ویس)
- 📝 خلاصه‌سازی گروه (`.summary [N]` — N پیام آخر)

### P2
- 📅 Scheduled messages (`.schedule "متن" 18:00`)
- ⚪ Whitelist / Blacklist برای AI
- 📊 آمار AI usage / tokens
- 🔍 فیلتر زمانی برای `.search` (مثلاً `.search ali --days 30`)

### P3
- 🎯 Per-group AI personality scoping
- 📈 Stats dashboard (وب)
- 🗂 پشتیبانی چند اکانت (multi-instance manager)
