# PRD — Bidar v1.2.0 (Always Online Telegram Userbot)

## Problem Statement
کاربر میخواد اکانت تلگرامش همیشه آنلاین باشه و پاسخ خودکار بده،
کنترلش فقط دست خودش باشه، و همه تنظیمات حیاتی قابل تغییر از داخل چت باشن.

## User Context
- یوزرنیم گیت‌هاب: `MamawliV2`
- محل اجرا: VPS (لینوکس)
- کتابخونه: Telethon

## v1.2.0 Updates (this iteration)
- ✅ دستور `.interval <ثانیه>` برای تنظیم بازه رفرش آنلاین
- ✅ پشتیبانی از فرمت دقیقه: `.interval 3m`
- ✅ محدوده مجاز: 30-300 ثانیه (با پیام خطای هوشمند)
- ✅ پیش‌فرض: 240s (۴ دقیقه)
- ✅ ذخیره پایدار در `bidar_config.json`
- ✅ `.stats` حالا بازه رفرش رو هم نشون میده
- ✅ `.help` آپدیت شد

## All Commands (10 total, همه owner-only)
| گروه | دستور | کاربرد |
|---|---|---|
| آنلاین | `.online on/off/toggle` | کنترل آنلاین |
| آنلاین | `.interval <s>` | تنظیم بازه رفرش |
| پاسخ | `.reply on/off/toggle` | پاسخ خودکار |
| پاسخ | `.setmsg <متن>` | ویرایش متن |
| پاسخ | `.afk [متن]` | میانبر |
| ابزار | `.ping`, `.alive`, `.stats`, `.id` | اطلاعات |
| مدیریت | `.restart`, `.help` | سیستم |

## Config Schema (bidar_config.json)
```json
{
  "online_enabled": true,
  "autoreply_enabled": false,
  "autoreply_message": "...",
  "autoreply_cooldown": 1800,
  "online_refresh_interval": 240
}
```

## Security
- Double-layer owner check: `outgoing=True` + `sender_id == OWNER_ID`
- `@owner_only` decorator on all 10 handlers (verified)
- `.env` با permission 600
- `.gitignore` شامل `bidar_config.json`, `.env`, `*.session`

## Tests Passed
- Python lint (ruff): all checks passed
- Regex pattern tests for `.interval` (4 variants)
- Config persistence (save/load roundtrip)
- All 10 commands have `@owner_only`

## File Structure
```
/app/bidar/
├── bidar.py              # 457 lines
├── install.sh            # 321 lines
├── bidar.service         # systemd template
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md             # 219 lines
```

## Next Action Items
- Save to GitHub → `github.com/MamawliV2/bidar`
- تست روی VPS واقعی

## Backlog (Future)
- P1: Night mode (AFK خودکار شبانه)
- P1: AI auto-reply با GPT
- P2: Whitelist/Blacklist
- P2: Scheduled messages
- P2: Web dashboard
