# PRD — Bidar v1.9.2 (Always Online Telegram Userbot + AI Assistant)

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

### v1.9.2 — Tidal / Apple Music / YouTube Music Fixes (Completed Jun 2026)
User-reported (screenshots): Tidal, Apple Music & YouTube Music all returned "no audio found" / "Couldn't read track info".
Root causes & fixes — all live E2E verified with the user's exact URLs:
- ✅ **Garbage DRM search queries**: Apple OG parse produced `'Duration 2:40 - Europapa by Joost on Apple Music'`, Tidal produced un-unescaped `'Listen to Let&#39;s... - Marvin Gaye - ...'` → both searches found nothing → "no audio found".
  - Apple → now resolved via official **iTunes Lookup API** (`?i=` param then path ID, with country) → `Joost - Europapa`
  - Deezer → official **Deezer API** (`api.deezer.com/track/{id}`)
  - Tidal/universal OG fallback → `html.unescape`, "TITLE by ARTIST on PLATFORM" og:title parsing, 'Artist - Title' og:title passthrough, junk filters (duration/listen-to)
  - New `_clean_query()` — strips `(Official Video)`, `- Single`, `\xa0`, HTML entities
- ✅ **`_music_download_sync` v1.9.1 edit had silently not landed** (parallel write race) — re-applied & verified: m4a/mp3 format preference, broader audio exts, largest-file pick, `.part` skip, **video-container (.mp4) last resort** (YouTube on restricted IPs may only offer progressive mp4 → previously "no audio found").
- ✅ **Direct YouTube/YT-Music links** blocked on server IPs → new fallback: title via **YouTube oEmbed** (works even when downloads are 403'd) → top-3 SoundCloud results.
- ✅ SC fallback now **skips uploads shorter than 60s** (30s Go+ previews snuck through as tiny files).
- ✅ Startup warning when ffmpeg is missing.
- ✅ NOTE: user's Apple album test link `…/blinding-lights/1499385311?i=1499385316` is a **dead link (HTTP 404, removed from catalog)** — correctly reports "Couldn't read track info"; valid album links with `?i=` now work.
- ✅ Tests: **59 passing** (12 new: clean-query, iTunes/Deezer/oEmbed lookups mocked, mp4 fallback, .part skip).

### v1.9.3 — YouTube Music–Only (Completed Jun 2026)
- ✅ **Only `music.youtube.com`** URLs are treated as music. Plain `youtube.com/watch`, `youtu.be`, `youtube.com/shorts`, `m.youtube.com` are intentionally ignored (auto-detect and `.sc <link>`) so the bot doesn't turn every shared video into an audio file.
- ✅ Platform label renamed to "YouTube Music" in audio captions.
- ✅ Regression test (`test_youtube_music_only`) added.

### v1.9.4 — Image Aspect-Ratio Control (Completed Jun 2026)
- ✅ New config key `image_aspect_ratio` (default `1:1`) + `.imgsize` command to view/set it
- ✅ `.img` and `.imgedit` accept inline `--ar 16:9` / `--landscape` / `--استوری` flags (per-image override without changing default)
- ✅ Friendly aliases: `square / مربعی`, `landscape / افقی`, `portrait / story / عمودی / استوری`, `cinematic / سینمایی`, `photo / عکس`, `tv / classic`
- ✅ Tolerant input parser: `16x9`, `16×9`, `16/9`, `16:9` all work
- ✅ Passed to Gemini Nano Banana / Pro Image via `image_config={"aspect_ratio": "..."}` through emergentintegrations' LlmChat → litellm → Google `generation_config.image_config`
- ✅ Live verified with real key: 1:1 → 1024×1024, 16:9 → 1376×768, 9:16 → 768×1376, 4:3 → 1200×896, 3:4 → 896×1200, 21:9 → 1584×672, 3:2 → 1264×848
- ✅ Supported ratios: `1:1, 16:9, 9:16, 4:3, 3:4, 21:9, 3:2, 2:3, 5:4, 4:5, 4:1, 1:4, 8:1, 1:8`
- ✅ Tests: **72 passing** (+13 new for aspect-ratio parser, flag extractor, generate_image AR passthrough)

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

## Test Results (Jun 2026 — v1.9.2)
✅ Syntax check passes (py_compile)
✅ `pytest tests/` — **59 passing** (test_search + test_soundcloud + test_music_universal; incl. v1.9.1 whitelist/shortlink tests and 12 new v1.9.2 tests: clean-query, iTunes/Deezer/YT-oEmbed lookups, mp4 fallback, .part skip)
✅ Real E2E (user's exact URLs, YouTube fully blocked in test env):
  - `on.soundcloud.com/aquUJP…` shortlink → 19MB mp3 downloaded
  - Spotify Europapa → oEmbed → SC #1 DRM skipped → SC #2 mp3 sent
  - Apple song & album(?i=) → iTunes API → "Joost - Europapa" → audio sent
  - Tidal → "Marvin Gaye - Let's Get It On" → full-length m4a sent (≥60s filter)
  - YouTube Music watch URL → oEmbed → SC fallback → m4a sent
  - Dead Apple link (404) → clean "Couldn't read track info" message
✅ Whitelist variants: raw `.id` style `2453861964` matches chat `-1002453861964`

## Next Action Items
- User: "Save to GitHub" then `bash update.sh` on VPS to deploy v1.9.2
- User verify in Telegram: Tidal / Apple Music / YouTube Music links in PV & allowed groups

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
