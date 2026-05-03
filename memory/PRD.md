# PRD — Bidar v1.1.0 (Always Online Telegram Userbot)

## Problem Statement
کاربر میخواد اکانت تلگرامش همیشه آنلاین باشه و پاسخ خودکار بده،
کنترلش فقط دست خودش باشه، و دستورات نصب/مدیریت رو ساده و اتوماتیک کنه.

## User Choices
- نام پروژه: **Bidar** (بیدار)
- یوزرنیم گیت‌هاب: `MamawliV2`
- کتابخونه: Telethon
- محل اجرا: VPS (لینوکس)

## v1.1.0 Updates (this iteration)
- ✅ **آنلاین واقعی**: تسک پس‌زمینه `online_keeper()` که هر ۴ دقیقه
     `UpdateStatusRequest(offline=False)` میفرسته — الان واقعاً به دیگران
     آنلاین نشون داده میشه
- ✅ **دستور `.online on|off`** برای کنترل وضعیت آنلاین
- ✅ **دستور `.reply on|off`** جدا از AFK برای پاسخ خودکار
- ✅ **دستور `.setmsg <متن>`** برای ویرایش متن پاسخ خودکار در زمان اجرا
- ✅ **تنظیمات پایدار** در `bidar_config.json` (بعد از ری‌استارت حفظ میشه)
- ✅ **Aliasهای فارسی** برای on/off (روشن/خاموش)
- ✅ یوزرنیم گیت‌هاب در install.sh و README به `MamawliV2` آپدیت شد

## All Commands (9 total, همه owner-only)
| دستور | کاربرد |
|---|---|
| `.online on/off` | آنلاین دائم |
| `.reply on/off` | پاسخ خودکار |
| `.setmsg <متن>` | ویرایش متن |
| `.afk [متن]` | میانبر AFK |
| `.ping` | تست تاخیر |
| `.alive` | زنده بودن |
| `.stats` | همه آمار + تنظیمات |
| `.id` | آیدی |
| `.restart` | ری‌استارت |
| `.help`/.menu/.commands | راهنما |

## Security
- Double-layer owner check: `outgoing=True` + `sender_id == OWNER_ID`
- Decorator `@owner_only` روی همه هندلرها (تست شد: هیچ handler بدون این دکوریتور نیست)
- `.env` با permission 600
- `.gitignore` شامل همه فایل‌های حساس

## File Structure
```
/app/bidar/
├── bidar.py              # 404 lines — logic
├── install.sh            # 321 lines — one-line installer
├── bidar.service         # systemd template
├── requirements.txt      # Telethon + python-dotenv
├── bidar_config.json     # runtime state (gitignored)
├── .env.example
├── .gitignore
└── README.md             # 216 lines
```

## Tests Passed
- Python lint (ruff): all checks passed
- Bash syntax check (bash -n): OK
- Module imports without errors
- Unit tests for `_fmt_uptime`, `_is_owner`, `_parse_on_off`
- JSON config persistence (save/load roundtrip)
- All 9 command handlers have `@owner_only`

## Next Action Items
- کاربر از Save to GitHub برای انتقال به `github.com/MamawliV2/bidar` استفاده کنه
- تست روی VPS واقعی با API credentials کاربر

## Backlog (Future)
- P1: AI auto-reply با GPT
- P1: Night mode (AFK خودکار در ساعات خاص)
- P2: Whitelist/Blacklist برای پاسخ خودکار
- P2: Scheduled messages
- P2: Web dashboard برای چند اکانت
