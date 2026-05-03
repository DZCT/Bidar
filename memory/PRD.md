# PRD — Bidar v1.3.0 (Always Online Telegram Userbot + AI Assistant)

## Problem Statement
یوزربات تلگرام همیشه آنلاین با قابلیت پاسخ خودکار هوشمند (GPT/Claude/Gemini از طریق Emergent Universal Key) که در چت خصوصی و گروه‌ها هم بتونه با context کار کنه.

## User Context
- یوزرنیم گیت‌هاب: `MamawliV2`
- ریپو: `MamawliV2/Bidar` (Private، با PAT)
- محل اجرا: VPS (Ubuntu 22.04.1)

## v1.3.0 Updates (AI Assistant Integration)
- ✅ ادغام `emergentintegrations.llm.chat` با Emergent Universal Key
- ✅ مدل پیش‌فرض: `gemini-3-flash-preview` (از سمت کاربر)
- ✅ پشتیبانی از GPT (5.2, 4o)، Claude (sonnet 4.5)، Gemini (3-flash, 2.5-pro)
- ✅ Context management: هر چت session جدا، مکالمه حفظ میشه
- ✅ **در گروه‌ها**: فقط وقتی mention یا reply شده پاسخ میده (با context گروه)
- ✅ شخصیت قابل تنظیم توسط کاربر (system prompt)
- ✅ Default persona: "جایگزین صاحب اکانت باش، طبیعی و کوتاه جواب بده"
- ✅ Fallback: اگه AI fail شد، به متن ثابت برمی‌گرده
- ✅ Cooldown در گروه: 30s (جلوگیری از spam)

## New Commands (5 AI commands)
| دستور | کاربرد |
|---|---|
| `.ai on/off` | روشن/خاموش AI master |
| `.aigroups on/off` | AI در گروه‌ها |
| `.personality <text>` | تنظیم شخصیت + ریست مکالمات |
| `.aimodel <model>` | تغییر مدل |
| `.aireset` | پاک کردن حافظه مکالمات |

Total: 15 commands (all `@owner_only`)

## Architecture
- Session mgmt: `dict[session_id, LlmChat]` در حافظه
- Session IDs:
  - `private_{user_id}` برای چت خصوصی
  - `group_{chat_id}` برای گروه
- Config persistence در `bidar_config.json`
- AI library import با try/except برای graceful degradation

## Tests Passed
- ✅ Python lint (ruff) all checks passed
- ✅ Bash syntax check
- ✅ Module loads, all 15 commands have `@owner_only`
- ✅ `_infer_provider()` tests (gemini/claude/openai/fallback)
- ✅ Config save/load AI fields
- ✅ **Real AI call test** with `sk-emergent-21fBf1c268194EaDfA`:
  - `gemini-3-flash-preview` responded naturally in Persian and English
  - Context maintained across 2 messages
  - Matches expected persona (no "I'm an AI" mentions)

## File Structure
```
/app/bidar/
├── bidar.py              # 717 lines (AI logic added)
├── install.sh            # 361 lines (AI prompt + emergentintegrations install)
├── README.md             # 538 lines (AI section added)
├── requirements.txt      # added emergentintegrations
├── .env.example          # added EMERGENT_LLM_KEY
├── bidar.service         # systemd template
├── LICENSE               # MIT
└── .gitignore
```

## Install Command (Private Repo with PAT)
```bash
export GH_TOKEN="github_pat_..."
bash <(curl -fsSL -H "Authorization: token $GH_TOKEN" \
  https://raw.githubusercontent.com/MamawliV2/Bidar/main/bidar/install.sh)
```

## Next Action Items
- کاربر Save to GitHub بزنه تا v1.3.0 push بشه
- روی VPS با دستور نصب آپدیت‌شده re-install کنه
- `.ai on` بزنه توی تلگرامش و تست کنه

## Backlog
- P1: Night mode (AFK/offline خودکار شبانه)
- P1: دستور نشون دادن تاریخچه AI usage / tokens
- P2: Whitelist/Blacklist برای AI
- P2: Scheduled messages
- P2: Custom session scoping (per-group personality)
