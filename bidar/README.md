<div align="center">

<img src="https://img.shields.io/badge/🌙-BIDAR-26A5E4?style=for-the-badge&labelColor=1a1a1a" alt="Bidar Logo" />

# Bidar — بیدار

### 🌙 یوزربات تلگرام همیشه آنلاین

**ساده • امن • قدرتمند**

_بیدار = همیشه بیدار، همیشه آنلاین_

<br />

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Telethon](https://img.shields.io/badge/Telethon-1.36+-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![Version](https://img.shields.io/badge/Version-1.2.0-success?style=flat-square)](https://github.com/MamawliV2/bidar/releases)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Persian](https://img.shields.io/badge/Language-فارسی-orange?style=flat-square)](#)

<br />

[نصب سریع](#-نصب-تکخطی) •
[دستورات](#-لیست-کامل-دستورات) •
[امنیت](#-امنیت) •
[رفع اشکال](#-رفع-اشکال) •
[توسعه](#-ایدههای-توسعه-بعدی)

</div>

---

## 📚 فهرست مطالب

- [درباره پروژه](#-درباره-پروژه)
- [قابلیت‌ها](#-قابلیتها)
- [پیش‌نیازها](#-پیشنیازها)
- [نصب تک‌خطی](#-نصب-تکخطی)
- [نصب دستی](#-نصب-دستی)
- [لیست کامل دستورات](#-لیست-کامل-دستورات)
- [نمونه سناریو](#-نمونه-سناریو)
- [امنیت](#-امنیت)
- [فایل پیکربندی](#-فایل-پیکربندی)
- [مدیریت سرویس](#-مدیریت-سرویس)
- [رفع اشکال](#-رفع-اشکال)
- [ساختار پروژه](#-ساختار-پروژه)
- [ایده‌های توسعه بعدی](#-ایدههای-توسعه-بعدی)
- [مجوز](#-مجوز)

---

## 📖 درباره پروژه

<div dir="rtl">

**Bidar** یه یوزربات تلگرام سبک و امن با Telethon هست که:

- ✅ اکانتت رو **۲۴/۷ واقعاً آنلاین** نشون میده
- ✅ با **پاسخ خودکار هوشمند**، پیام‌های خصوصی رو مدیریت میکنه
- ✅ همه تنظیمات رو **توی چت خود تلگرام** می‌تونی لایو تغییر بدی
- ✅ دستورات **فقط مالک اکانت** کنترل میکنه — دو لایه امنیتی داره

</div>

> **💡 فرق Bidar با بقیه یوزربات‌ها:**
> خیلی از یوزربات‌ها فقط "متصل" هستن، ولی Bidar با ارسال دوره‌ای `UpdateStatusRequest` به سرور تلگرام، واقعاً شما رو "آنلاین" نشون میده.

---

## ✨ قابلیت‌ها

<div dir="rtl">

| 🎯 | قابلیت | توضیح |
|:---:|:---|:---|
| 🟢 | **آنلاین واقعی** | ارسال خودکار `UpdateStatusRequest` با بازه قابل تنظیم |
| ⏱ | **بازه قابل تنظیم** | از ۳۰ تا ۳۰۰ ثانیه، با دستور `.interval` در چت |
| 💤 | **پاسخ خودکار** | قابل خاموش/روشن و ویرایش متن در زمان اجرا |
| 💾 | **تنظیمات پایدار** | ذخیره خودکار در `bidar_config.json` |
| 🔒 | **قفل مالکیت** | دولایه امنیتی — فقط مالک دستور میزنه |
| ⏳ | **Cooldown هوشمند** | جلوگیری از اسپم با ارسال یک پاسخ به هر کاربر در بازه زمانی |
| 🛡 | **فقط چت خصوصی** | گروه‌ها، کانال‌ها و ربات‌ها نادیده گرفته میشن |
| 📊 | **آمار زنده** | آپ‌تایم، تعداد پیام‌ها و پاسخ‌ها |
| 📝 | **لاگ فایل** | همه رویدادها برای بررسی ثبت میشن |
| 🔄 | **ری‌کانکت خودکار** | در صورت قطعی، خودش دوباره وصل میشه |

</div>

---

## 📋 پیش‌نیازها

<div dir="rtl">

- سرور VPS لینوکسی (Ubuntu 20.04+ / Debian 11+ پیشنهادی)
- **Python 3.10+**
- API ID و API Hash از [my.telegram.org/apps](https://my.telegram.org/apps)
- شماره موبایلی که اکانت تلگرامت روش فعاله
- دسترسی `root` یا `sudo`

> ⚠️ در حین نصب، اسکریپت پیش‌نیازها رو خودش بررسی و نصب می‌کنه.

</div>

---

## 🚀 نصب تک‌خطی

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/MamawliV2/bidar/main/install.sh)
```

<div dir="rtl">

اسکریپت نصب به صورت کاملاً خودکار:

1. ✅ پیش‌نیازها رو چک می‌کنه (Python 3.10+, pip, venv, git, curl)
2. ✅ هر چی نصب نباشه رو نصب می‌کنه (apt / dnf / yum / pacman / apk)
3. ✅ سورس رو کلون می‌کنه توی `/opt/bidar`
4. ✅ محیط مجازی پایتون می‌سازه و وابستگی‌ها رو نصب می‌کنه
5. ✅ تعاملی ازت می‌پرسه: API_ID، API_HASH، شماره موبایل، متن AFK
6. ✅ لاگین اولیه (کد تایید رو از تلگرام دریافت می‌کنی و وارد می‌کنی)
7. ✅ سرویس `systemd` می‌سازه تا Bidar دائمی بالا بمونه

</div>

---

## 📥 نصب دستی

<details>
<summary><b>کلیک کن برای دیدن مراحل</b></summary>

```bash
# کلون پروژه
git clone https://github.com/MamawliV2/bidar.git /opt/bidar
cd /opt/bidar

# ساخت محیط مجازی
python3 -m venv venv
source venv/bin/activate

# نصب وابستگی‌ها
pip install -r requirements.txt

# پیکربندی
cp .env.example .env
nano .env    # مقادیر API_ID, API_HASH, PHONE رو پر کن

# اجرای اولیه (برای لاگین با کد SMS)
python bidar.py

# بعد از لاگین موفق، Ctrl+C و راه‌اندازی به عنوان سرویس
sudo cp bidar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bidar
```

</details>

---

## 💬 لیست کامل دستورات

> 🔒 همه دستورات **فقط** وقتی از اکانت خودت تایپ بشن کار می‌کنن.

### 📡 وضعیت آنلاین

<div dir="rtl">

| دستور | کاربرد |
|:---|:---|
| `.online on` | روشن کردن آنلاین دائم |
| `.online off` | خاموش کردن (آفلاین نشون داده میشی) |
| `.online` | جابه‌جا (toggle) |
| `.interval <ثانیه>` | تنظیم بازه رفرش آنلاین (پیش‌فرض ۲۴۰ = ۴ دقیقه) |
| `.interval 3m` | پشتیبانی از فرمت دقیقه |
| `.interval` | نمایش مقدار فعلی و محدوده مجاز |

</div>

### 🤖 پاسخ خودکار

<div dir="rtl">

| دستور | کاربرد |
|:---|:---|
| `.reply on` | روشن کردن پاسخ خودکار |
| `.reply off` | خاموش کردن |
| `.reply` | جابه‌جا (toggle) |
| `.setmsg <متن>` | ویرایش متن پاسخ خودکار |
| `.afk <متن>` | میانبر: متن جدید + روشن کردن پاسخ |
| `.afk off` | خاموش کردن سریع |

</div>

### 📊 اطلاعات و ابزار

<div dir="rtl">

| دستور | کاربرد |
|:---|:---|
| `.help` / `.menu` / `.commands` | راهنمای کامل |
| `.alive` | چک زنده بودن ربات |
| `.ping` | تست تاخیر پاسخ (ms) |
| `.stats` | همه آمار و تنظیمات فعلی |
| `.id` | آیدی چت فعلی (و کاربر اگه ریپلای بزنی) |
| `.restart` | ری‌استارت سرویس (در حالت systemd) |

</div>

---

## 🎬 نمونه سناریو

<div dir="rtl">

فرض کن می‌خوای بری بیرون و تا ۶ برنمی‌گردی:

</div>

```
.setmsg سلام 👋 تا ۶ بعدازظهر برمیگردم، بعدش جواب میدم 🙏
.reply on
.stats
```

<div dir="rtl">

خروجی `.stats`:

</div>

```
📊 آمار و تنظیمات Bidar

⏱ آپ‌تایم: 2h 15m 30s
📡 آنلاین دائم: روشن 🟢
🔄 بازه رفرش آنلاین: 240s (~4m)
🤖 پاسخ خودکار: روشن 🟢
📨 پیام‌های خصوصی دریافتی: 12
✉️ پاسخ‌های خودکار ارسالی: 8
⏳ Cooldown پاسخ: 1800s

📝 متن پاسخ خودکار:
سلام 👋 تا ۶ بعدازظهر برمیگردم، بعدش جواب میدم 🙏
```

---

## 🔒 امنیت

<div dir="rtl">

Bidar با چند لایه امنیتی طراحی شده:

**۱. دو لایه چک مالک اکانت**

- لایه اول: `outgoing=True` → فقط پیام‌های ارسالی از اکانت خودت trigger میشن
- لایه دوم: دکوریتور `@owner_only` با چک صریح `sender_id == OWNER_ID`

**۲. بدون ذخیره پسورد**

فقط فایل `.session` تلگرام استفاده میشه — هیچ پسوردی ذخیره نمیشه.

**۳. مجوزهای محدود فایل‌ها**

- `.env` با permission 600 (فقط مالک می‌تونه بخونه)
- `.gitignore` شامل همه فایل‌های حساس

**۴. فقط چت خصوصی**

پاسخ خودکار توی گروه‌ها و کانال‌ها داده نمیشه (جلوگیری از اسپم).

### 🛡 توصیه‌های مهم

- ✅ حتماً **2FA** روی اکانت تلگرامت فعال کن
- ✅ `API_ID`, `API_HASH`, `*.session` رو هیچ جای عمومی نذار (گیت‌هاب پابلیک، پیست‌بین، ...)
- ✅ در صورت امکان، سرویس رو زیر یه یوزر غیر root اجرا کن
- ✅ دسترسی SSH به VPS رو با کلید (نه پسورد) محدود کن

</div>

---

## ⚙️ فایل پیکربندی

<div dir="rtl">

تنظیمات runtime در فایل `bidar_config.json` ذخیره میشن:

</div>

```json
{
  "online_enabled": true,
  "autoreply_enabled": false,
  "autoreply_message": "سلام 👋 الان در دسترس نیستم...",
  "autoreply_cooldown": 1800,
  "online_refresh_interval": 240
}
```

<div dir="rtl">

> 💡 **نکته:** نیازی نیست این فایل رو دستی ویرایش کنی. همه تنظیمات از داخل چت تلگرام با دستورات قابل تغییرن.

</div>

---

## 🧰 مدیریت سرویس

```bash
# وضعیت سرویس
sudo systemctl status bidar

# ری‌استارت
sudo systemctl restart bidar

# توقف
sudo systemctl stop bidar

# شروع
sudo systemctl start bidar

# لاگ زنده (Ctrl+C برای خروج)
sudo journalctl -u bidar -f

# لاگ فایل
tail -f /opt/bidar/bidar.log
```

---

## 🐛 رفع اشکال

<details>
<summary><b>سرویس بالا نمیاد</b></summary>

```bash
sudo journalctl -u bidar -n 100 --no-pager
tail -100 /opt/bidar/bidar.err.log
```

<div dir="rtl">

- بررسی کن `.env` درست پر شده
- بررسی کن venv ساخته شده: `ls /opt/bidar/venv/bin/python`
- اگه بعد از لاگین اولیه هنوز کد می‌خواد، فایل `bidar_session.session` ساخته نشده — دستی اجرا کن

</div>

</details>

<details>
<summary><b>دیگران منو «آنلاین» نمی‌بینن</b></summary>

<div dir="rtl">

۱. مطمئن شو `.online` روشنه:
</div>

```
.stats
```

<div dir="rtl">

۲. تنظیمات privacy تلگرامت رو چک کن:
- `Settings → Privacy and Security → Last Seen & Online`

۳. چند دقیقه صبر کن تا اولین رفرش انجام بشه.

۴. اگه هنوز مشکل داشت:
</div>

```bash
tail -20 /opt/bidar/bidar.log
```

</details>

<details>
<summary><b>آیا اکانتم بن میشه؟</b></summary>

<div dir="rtl">

Bidar **اسپم نمی‌کنه** — فقط به پیام‌های خصوصی با cooldown پاسخ میده. ولی برای امنیت بیشتر:

- از اکانت‌های قدیمی‌تر (بالای ۶ ماه) استفاده کن
- `autoreply_cooldown` رو پایین‌تر از ۶۰۰ ثانیه (۱۰ دقیقه) نذار
- `interval` کمتر از ۳۰ ثانیه بی‌مورده و ممکنه مشکل‌ساز بشه

</div>

</details>

<details>
<summary><b>چطور متن پاسخ خودکار رو با چند خط تنظیم کنم؟</b></summary>

<div dir="rtl">

تلگرام دسکتاپ: `Shift + Enter` برای خط جدید، بعد همه رو Enter نهایی بزن:

</div>

```
.setmsg سلام 👋
الان در جلسه‌ام
بعد از ساعت ۴ برمیگردم 🙏
```

</details>

<details>
<summary><b>میخوام چند اکانت رو همزمان بالا نگه دارم</b></summary>

<div dir="rtl">

Bidar فعلاً تک‌اکانت طراحی شده. برای چند اکانت:

- هر اکانت رو توی یه مسیر جدا نصب کن (مثلاً `/opt/bidar-acc1`, `/opt/bidar-acc2`)
- `SESSION_NAME` رو در `.env` هر کدوم متفاوت بذار
- سرویس systemd جداگانه برای هر کدوم بساز

</div>

</details>

---

## 📁 ساختار پروژه

```
bidar/
├── bidar.py              # اسکریپت اصلی (~ 450 خط)
├── install.sh            # نصاب اتوماتیک (~ 320 خط)
├── bidar.service         # تمپلیت سرویس systemd
├── requirements.txt      # وابستگی‌های پایتون
├── .env.example          # نمونه متغیرهای محیطی
├── .gitignore            # جلوگیری از آپلود فایل‌های حساس
├── README.md             # همین فایل
└── bidar_config.json     # تنظیمات پایدار (بعد از اولین اجرا)
```

---

## 🎯 ایده‌های توسعه بعدی

<div dir="rtl">

| اولویت | قابلیت | توضیح |
|:---:|:---|:---|
| 🔥 | **حالت شب** | AFK خودکار در ساعات خاص (مثلاً ۰۰:۰۰ تا ۰۷:۰۰) |
| 🔥 | **دستیار AI** | پاسخ خودکار هوشمند با GPT بر اساس پیام |
| ⭐ | **لیست سفید/سیاه** | مخاطبین خاص پاسخ خودکار نگیرن |
| ⭐ | **پیام زمان‌بندی‌شده** | ارسال پیام در زمان مشخص |
| 💡 | **داشبورد وب** | مدیریت چند اکانت با GUI |
| 💡 | **آمار گراف** | نمایش آمار در بازه زمانی |

</div>

> 🤝 اگه ایده یا pull request داری، خوشحال می‌شم که ببینم!

---

## 🤝 مشارکت

<div dir="rtl">

همه فرم‌های مشارکت خوش‌اومدن:

1. ⭐ **Star** دادن به ریپو
2. 🐛 گزارش باگ در [Issues](https://github.com/MamawliV2/bidar/issues)
3. 💡 پیشنهاد قابلیت جدید
4. 🔧 Pull Request

</div>

---

## 📜 مجوز

<div dir="rtl">

این پروژه تحت مجوز **MIT** منتشر شده. برای جزئیات [LICENSE](LICENSE) رو ببین.

</div>

---

<div align="center">

**ساخته شده با ❤️ برای آدم‌های پرمشغله ✨**

<br />

[⭐ Star on GitHub](https://github.com/MamawliV2/bidar) •
[🐛 Report Bug](https://github.com/MamawliV2/bidar/issues) •
[💡 Request Feature](https://github.com/MamawliV2/bidar/issues)

<br />

<sub>Bidar v1.2.0 — 2026</sub>

</div>
