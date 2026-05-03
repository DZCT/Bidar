# PRD — Telegram Userbot (Always Online)

## Problem Statement
کاربر میخواد اکانت تلگرامش به صورت دائمی آنلاین باشه. گزینه ساده (اسکریپت پایتون با Telethon روی VPS) انتخاب شد.

## User Choices
- کتابخونه: Telethon
- محل اجرا: VPS (لینوکس)
- قابلیت‌ها: آنلاین + پاسخ خودکار + امکانات اضافه

## Architecture
- **زبان:** Python 3.10+
- **کتابخونه اصلی:** Telethon >= 1.36.0
- **اجرا:** systemd service روی VPS
- **احراز هویت:** فایل `.session` تلگرام (اولین بار با کد SMS)

## Implemented Features (May 2026)
- Always-online via Telethon `run_until_disconnected`
- Auto-reconnect on error (retry loop)
- AFK mode با متن دلخواه (`.afk [reason]`)
- Per-user cooldown برای جلوگیری از اسپم
- دستورات داخلی: `.ping`, `.alive`, `.stats`, `.id`, `.help`
- فقط چت خصوصی پاسخ خودکار میگیره (گروه/کانال/بات رد میشه)
- لاگ فایل + استریم stdout
- systemd service template
- `.gitignore` برای محافظت از `.env` و `.session`

## File Structure
```
/app/telegram_userbot/
├── userbot.py          # اسکریپت اصلی
├── requirements.txt    # وابستگی‌ها
├── .env.example        # نمونه env
├── .gitignore
├── userbot.service     # systemd unit
└── README.md           # راهنمای کامل فارسی
```

## Backlog (Potential Features)
- P1: دستیار هوش مصنوعی با GPT برای پاسخ هوشمند
- P1: حالت شب (AFK خودکار در ساعات خاص)
- P2: لیست سفید/سیاه مخاطبین
- P2: پیام زمان‌بندی‌شده
- P2: داشبورد وب برای مدیریت چند اکانت
- P3: ذخیره خودکار فایل‌ها / مدیا در دیسک یا S3

## Next Action Items
- کاربر باید `.env` رو با API_ID / API_HASH / PHONE خودش پر کنه
- اولین اجرا روی VPS برای تایید کد SMS
- انتقال به systemd و enable کردن سرویس

## Security Notes
- `.env` و `.session` نباید در گیت پابلیک بره
- توصیه شده 2FA تلگرام فعال باشه
- chmod 600 روی فایل‌های حساس
