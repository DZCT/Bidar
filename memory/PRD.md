# PRD — Bidar (Always Online Telegram Userbot)

## Problem Statement
کاربر میخواد اکانت تلگرامش به صورت دائمی آنلاین باشه + پاسخ خودکار + دستورات سفارشی که فقط مالک اکانت بتونه کنترلش کنه.

## User Choices
- نام پروژه: **Bidar** (بیدار)
- کتابخونه: Telethon
- محل اجرا: VPS (لینوکس)
- امنیت: فقط مالک اکانت بتونه دستور بزنه
- نصب: اسکریپت تک‌خطی اتوماتیک

## Implemented Features (May 2026)
- ✅ همیشه آنلاین با ری‌کانکت خودکار
- ✅ پاسخ خودکار AFK با cooldown
- ✅ **دولایه امنیتی**: `outgoing=True` + صریح `sender_id == OWNER_ID`
- ✅ دکوریتور `@owner_only` روی تمام دستورات
- ✅ دستورات: `.help`, `.alive`, `.ping`, `.stats`, `.afk`, `.id`, `.restart`
- ✅ `.help` جامع با توضیحات کامل هر دستور
- ✅ `install.sh` اتوماتیک با:
  - تشخیص پکیج منیجر (apt/dnf/yum/pacman/apk)
  - نصب پیش‌نیازها (python3, venv, pip, git, curl)
  - کلون از گیت‌هاب یا استفاده از فایل‌های محلی
  - ساخت venv و نصب deps
  - دریافت تعاملی API_ID/HASH/PHONE از /dev/tty
  - نوشتن .env با permission 600
  - لاگین اولیه تعاملی
  - نصب systemd service با تمپلیت پویا
- ✅ README کامل فارسی با badges و troubleshooting
- ✅ `.gitignore` برای محافظت از .env و .session

## File Structure
```
/app/bidar/
├── bidar.py            # اسکریپت اصلی (272 lines)
├── install.sh          # نصاب تک‌خطی (321 lines)
├── bidar.service       # تمپلیت systemd با placeholder
├── requirements.txt    # Telethon + python-dotenv
├── .env.example        # نمونه تنظیمات
├── .gitignore
└── README.md           # راهنمای کامل فارسی
```

## Next Action Items
- آپلود به گیت‌هاب (کاربر خودش انجام بده با Save to GitHub)
- تست روی VPS واقعی (نیاز به API credentials کاربر)

## Backlog
- P1: دستیار هوش مصنوعی با GPT برای پاسخ هوشمند
- P1: حالت شب (AFK خودکار در ساعات خاص)
- P2: لیست سفید/سیاه برای AFK
- P2: پیام زمان‌بندی‌شده
- P2: داشبورد وب برای مدیریت چند اکانت
