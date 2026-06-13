# PRD — Bidar v1.9.1 (Always Online Telegram Userbot + AI Assistant)

## Problem Statement
یوزربات تلگرام همیشه آنلاین با قابلیت پاسخ خودکار هوشمند (GPT/Claude/Gemini از طریق Emergent Universal Key) که در چت خصوصی و گروه‌ها هم بتونه با context کار کنه + ابزارهای جانبی AI (ترجمه، تولید/ویرایش تصویر، OCR، جستجوی جهانی، رابط دوزبانه).

## User Context
- یوزرنیم گیت‌هاب: `DZCT`
- ریپو: `DZCT/Bidar` (Private، با PAT)
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

### v1.8.0 — SoundCloud Music Download (Completed Jun 2026)
- ✅ `.sc <link>` — direct download from SoundCloud link (soundcloud.com / on.soundcloud / api.soundcloud / snd.sc)
- ✅ `.sc <song name>` — search SoundCloud (`scsearch5:`), show top 5 results (title, artist, duration)
- ✅ `.sc <1-5>` — download a result from last search (per-chat result memory `_sc_results`)
- ✅ Sent as Telegram audio with title/performer/duration attributes + album cover thumbnail
- ✅ Prefers progressive MP3; converts to MP3 192k when ffmpeg available (yt-dlp postprocessor)
- ✅ Blocking yt-dlp calls run via `asyncio.to_thread` (no event-loop blocking)
- ✅ File sent in same chat as reply; temp dir cleaned up always
- ✅ `yt-dlp` added to requirements.txt; ffmpeg added to install.sh prereqs + update.sh `ensure_ffmpeg`
- ✅ Bilingual UI keys (11 keys) + help menu entries
- ✅ Unit test: `tests/test_soundcloud.py` — 48 checks, all passing + real E2E download verified

### v1.9.0 — Universal Music Downloader + Auto-Detect + Whitelist (Completed Feb 2026)
- ✅ **`.sc <link>` accepts any music platform**: SoundCloud, YouTube, YouTube Music, Bandcamp, Mixcloud, Yandex (direct via yt-dlp) + Spotify, Deezer, Apple Music, Tidal (DRM fallback via metadata → YouTube)
- ✅ Spotify metadata extraction via official **oEmbed** + embed page JSON (bypasses Spotify bot detection)
- ✅ Deezer/Apple/Tidal extraction via OpenGraph meta tags with smart parsing (handles `Song · Artist · Year`, `Artist - song - year`, `Listen to X by Y`)
- ✅ **Auto-detect**: incoming music links in PV (always) and whitelisted groups → auto-downloaded and replied as audio
- ✅ `.music on|off` — global toggle for auto-detect feature
- ✅ Per-chat URL dedup (5min cooldown for same link)
- ✅ **`.allow` whitelist command** (unified for AI + Music in groups):
  - `.allow here` / `.allow rmhere` — add/remove current chat
  - `.allow add/remove <chat_id>` — by numeric ID
  - `.allow list` / `.allow clear`
- ✅ Group AI replies now require chat_id in `allowed_groups` list (in addition to mention/reply trigger)
- ✅ Bilingual UI keys (15+ new keys: music_*, allow_*) + updated help menu
- ✅ Fixed shallow-copy bug in config init (deepcopy of _DEFAULT_CONFIG)
- ✅ Unit tests: `tests/test_music_universal.py` — 25 tests covering URL detection (10 platforms), DRM metadata mocks, allow-list persistence, auto-detect flow, dedup, i18n keys
- ✅ Real E2E verified: Spotify "Blinding Lights" → resolved to "The Weeknd - Blinding Lights" → yt-dlp found on YouTube

### v1.9.1 — Music Bug-Fix Release (Completed Jun 2026)
User-reported bugs (with screenshots) — all fixed & E2E verified:
- ✅ **`on.soundcloud.com` short share-links** now detected (regex allowed only www/m subdomains → links fell into search mode → "No results found"). Also added `spotify.link` & `deezer.page.link` shorteners (resolved via `_resolve_redirect`).
- ✅ **Spotify "no audio file"** fixed — three-layer fix:
  - yt-dlp format pref now `bestaudio[ext=m4a]/bestaudio[ext=mp3]/...` (proper audio file even without ffmpeg; old code could end up with `.webm` not in audio_exts)
  - broader audio_exts (incl. `.webm`, `.oga`, `.mka`) + largest-file pick, skip `.part`/`.ytdl`
  - **DRM fallback chain**: `ytsearch1:` → top-3 SoundCloud results (YouTube returns HTTP 403 on most datacenter IPs; first SC result may be DRM Go+ — loop skips to next). Verified live: Spotify→ Joost "Europapa" delivered via SC result #2.
- ✅ **Whitelisted groups never matched** — root cause: `.id` showed the raw positive entity ID (e.g. `2453861964`) while whitelist check compared against marked `-100…` form. Added `_chat_id_variants()` normalization — any ID form now matches (`_is_chat_allowed`). `.id` now shows the marked `event.chat_id`. `.allow add/remove/here/rmhere` are variant-aware.
- ✅ **Owner's own links now auto-detected** — new `outgoing=True` handler (PV + whitelisted groups); replies instead of editing (never destroys the original message). Bot's own status messages excluded via emoji-prefix guard.
- ✅ Music auto-detect now also covers links posted by **bots/channels** in whitelisted groups.
- ✅ Failed downloads **clear the dedup entry** → immediate retry possible (before: 5-min silent window after failure).
- ✅ DRM metadata failure now shows a clear bilingual error (`music_meta_failed`) instead of garbage-searching the URL on YouTube.
- ✅ Removed dead `_SC_URL_RE`; tests migrated to `_detect_music_url`.
- ✅ Tests: 47 passing (22 new in `test_music_universal.py` for shortlinks, chat-ID variants, outgoing flow, dedup-retry).

## Commands Summary (v1.9.1)
**Total: 33+ commands**, all `@owner_only`

| Category | Commands |
|---|---|
| Online | `.online`, `.interval` |
| Auto-reply | `.reply`, `.setmsg`, `.afk` |
| AI | `.ai`, `.aigroups`, `.personality`, `.aimodel`, `.aireset`, `.groupcd`, `.r` |
| Translation | `.lang`, `.tl`, `.to` |
| Image | `.img`, `.imgedit`, `.imgmodel`, `.ocr` |
| Search | `.search`, `.searchall` |
| Music | `.sc` (universal — link/search/pick), `.music` (auto-detect toggle) |
| Whitelist | `.allow` (add/remove/here/rmhere/list/clear) |
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
  https://raw.githubusercontent.com/DZCT/Bidar/main/bidar/install.sh)
```

## Test Results (Feb 2026 — v1.9.0)
✅ Syntax check passes (py_compile + lint clean)
✅ `tests/test_search.py` — all passing
✅ `tests/test_soundcloud.py` — 48 checks passing (legacy + new universal helpers)
✅ `tests/test_music_universal.py` — 25 tests passing (URL detection, DRM metadata, allow-list, auto-detect flow, dedup, i18n)
✅ Real E2E: Spotify oEmbed/embed parser → "The Weeknd - Blinding Lights" / "Ed Sheeran - Shape of You"; Deezer OG parser → "Eminem - Drips"
✅ yt-dlp ytsearch1 fallback verified end-to-end on YouTube

## Next Action Items
- User to run `bash update.sh` on VPS to deploy v1.9.0
- Test in Telegram: `.sc <spotify-link>`, `.sc <apple-music-link>`, then send a link in PV to verify auto-detect, then `.allow here` in a group + send link to verify whitelist
- "Save to GitHub" to push v1.9.0 to `DZCT/Bidar`

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
