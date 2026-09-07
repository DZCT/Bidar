# PRD — Bidar v1.10.0 (Always Online Telegram Userbot + AI Assistant)

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

### v1.19.0 — `.mergetxt` Merge all .txt files of a chat (Completed Jul 2026)
User request: give a channel/group link and merge all its `.txt` files into one `.txt`.
- ✅ `.mergetxt <link/@username/id>` resolves the chat (`get_entity` + `_normalize_chat_ref` for links/@user/numeric); `.mergetxt` with no arg uses the current chat
- ✅ Server-side filtered iteration (`InputMessagesFilterDocument`, oldest→newest), keeps only `.txt` / `text/plain`, downloads each and appends under a `===== FILE n: name =====` header to a temp file (written incrementally, not held in RAM)
- ✅ Live progress edits every 3s; 500 MB combined cap (flagged with `+`); nice caption (chat title · file count · size); output named `<title>_merged_<n>txt.txt`; graceful bad-link / no-files handling; temp dir cleaned; processing message deleted (guarded)
- ✅ Alias `.txtmerge`; bilingual i18n + help menu; caption icon 📚 added to `_BOT_MSG_PREFIXES`; version 1.19.0
- ✅ Tests: **236 passing** (+6: TestNormalizeChatRef, TestCmdMergeTxt — merges 2 files, skips non-txt PDF, handles empty chat)

### v1.18.0 — `.cp` Checkout link generator (Completed Jul 2026)
User request: a `.cp` command that calls their own endpoint (`CHECKOUT_API_URL`, default `http://155.103.70.111:5000/api/chatgpt/gen`) which returns a Stripe checkout link + generated credentials, and displays it.
- ✅ `.cp` → GET the endpoint (in a thread), parse JSON `{status,url,email,password}`, show a card: clickable "Open Checkout Page" link + copyable raw URL + email/password
- ✅ Endpoint is configurable via `CHECKOUT_API_URL` env var; graceful failure on bad status / non-JSON / connection error
- ✅ Bilingual i18n + help menu (`⚙️ System`) + version 1.18.0
- ✅ Tests: **230 passing** (+4: TestCmdCheckout) + real E2E against the live endpoint (returned a real `cs_live_...` Stripe URL)

### v1.17.0 — `.file` Text → File (Completed Jun 2026)
New feature (user request): turn text into a downloadable file with a chosen extension.
- ✅ `.file <ext> <text>` → creates `file.<ext>` from the text and sends it (as a document)
- ✅ `.file <name.ext> <text>` → use a full custom filename (e.g. `config.json`)
- ✅ **reply** to any message + `.file <ext>` → turns that message's text into a file
- ✅ Multiline content supported (paste code after the extension); UTF-8 (Persian-safe)
- ✅ `_build_filename` sanitizes path chars, handles bare ext / dotted-ext / full name, defaults to `.txt`; always `force_document=True`; compact caption (name · size); temp dir cleaned; processing message deleted (guarded)
- ✅ Aliases `.mkfile` / `.tofile`; bilingual i18n + help menu; version 1.17.0
- ✅ Tests: **226 passing** (+11: TestBuildFilename, TestCmdMkfile) + real E2E (multiline .py, full-name .json, reply→.srt)

### v1.16.1 — `.server` redesigned as an aligned ASCII card (Completed Jun 2026)
User asked for a much prettier, real-time ASCII-styled `.server` output.
- ✅ `_format_server_status` rewritten to render a **fixed-width ASCII box** (┌─┤│└ frame) inside a monospace ``` code block ``` so bars & columns stay perfectly aligned on every Telegram client
- ✅ New `_ascii_bar(pct, width=16)` (█/░) for the CPU/RAM/DISK bars; localized bold header line (`🖥 Live Server Status` / `وضعیت لحظه‌ای سرور`) sits above the box; ASCII labels inside for alignment (no emoji/RTL inside the frame)
- ✅ Added an alignment regression test (`test_format_lines_aligned`) ensuring every framed row is identical width; updated en/fa/temp tests
- ✅ Tests: **217 passing**. Version 1.16.1

### v1.16.0 — `.docx` support for `.ask` + `.server` VPS status (Completed Jun 2026)
Two user requests: (1) read/ask Word `.docx` files; (2) a stylish server-resource command.
- ✅ **`.ask` now reads Word `.docx`** via `python-docx` (paragraphs + table cells). Detected by extension or OOXML mime; guarded `DOCX_LIB_OK` import + `ask_docx_lib` install hint. Usage/help text updated to mention Word. Live-verified: docx → grounded AI answers ("20 days", "Tehran").
- ✅ **`.server`** (aliases `.sys` / `.vps`): a beautiful bilingual resource card — CPU (with % bar + core count + temp if available), RAM, Disk (all with `_progress_bar`), load average, network ↑/↓, server uptime, bot uptime, OS/Python, hostname. Powered by `psutil` (guarded `PSUTIL_OK`; `pip install psutil` hint if missing). CPU sampled via `asyncio.to_thread` (non-blocking).
- ✅ New helpers: `_extract_docx_text`, `_fmt_uptime` (renamed to avoid clash with existing `_fmt_duration`), `_gather_server_status`, `_format_server_status`. Reuses `_human_size` / `_progress_bar`.
- ✅ New deps: `python-docx==1.2.0`, `psutil==7.2.2` (added to requirements.txt). Help menu (`⚙️ System`) + `_BOT_MSG_PREFIXES` (🖥) updated. Version 1.16.0.
- ✅ Tests: **215 passing** (+8: TestDocxSupport, TestServerStatus, TestServerGather) + real E2E (docx AI Q&A + live server card in en/fa).

### v1.15.0 — `.ask` Document Q&A (Chat with a PDF/text file) (Completed Jun 2026)
New feature (user request): analyse a PDF or text file, then answer any question about it — multi-turn.
- ✅ `.ask` (alias `.pdf`): **reply to a file** to load & analyse it; `.ask <question>` on the reply answers immediately; subsequent `.ask <q>` (no reply) are **follow-ups** on the cached document (keeps last ~6 Q&A for context)
- ✅ `.ask reset` (also `clear`/`forget`/`پاک`/`فراموش`) clears the per-chat cache
- ✅ Supported: **PDF** (via `pypdf`, extracted page-by-page) + text files (txt, md, csv, json, code, yaml, html, srt, …). Scanned/image-only PDFs are detected → user pointed to `.ocr`
- ✅ Downloaded to bytes (25 MB cap), extracted in-memory, capped at 100k chars (~25k tokens), truncation flagged. Answers grounded strictly in the document, in the SAME language as the question
- ✅ New helpers: `_doc_is_supported`, `_extract_document_text`, `_answer_document` (uses `config["ai_model"]` = gemini-3-flash), `_reply_long` (chunked >4096 output); in-memory `_doc_cache` keyed by chat_id
- ✅ New dep: `pypdf==6.14.2` (added to requirements.txt); optional import guarded (`PDF_LIB_OK`) so the bot still runs without it
- ✅ Bilingual i18n + help menu (`📰 Web` section) + version 1.15.0
- ✅ Tests: **207 passing** (+16: TestDocHelpers, TestAnswerDocument, TestCmdAskFlow) + real E2E (real dummy.pdf extracted; markdown doc → correct grounded answers for "2 GB"/"nova"; multi-turn follow-up correctly answered "Python")

### v1.14.0 — `.mix` Combine Two Images (Completed Jun 2026)
New feature (user request): merge/blend two images into one via Gemini Nano Banana — with an optional prompt.
- ✅ `.mix [prompt]` (aliases `.combine` / `.merge`): if a prompt is given it guides the composition; without one, the two images are blended automatically
- ✅ Two ways to supply images: (1) **reply** to one image + **attach** a second image to the `.mix` message; (2) **reply to an album** (two photos sent together — gathered via `get_messages` window filtered by `grouped_id`)
- ✅ Optional aspect-ratio flag reused from `.img` (e.g. `.mix --16:9 ...`)
- ✅ New `_combine_images()` passes **multiple `ImageContent`** to `send_message_multimodal_response` (live-verified: 2 refs in → 1 combined image out)
- ✅ Helpers: `_msg_has_image`, `_gather_mix_images` (album + reply + own-attachment collection, capped at 2)
- ✅ Reuses `_friendly_image_error` for safety-filter/budget errors; processing message deleted via the same guarded pattern as the v1.13.1 fix; caption icon 🎭 added to `_BOT_MSG_PREFIXES`
- ✅ Bilingual i18n + help menu (`🎨 Image` section) + version 1.14.0
- ✅ Tests: **195 passing** (+13: `TestMsgHasImage`, `TestCombineImages`, `TestCmdMixFlow`) + real E2E (2 httpbin images → 917 KB combined image, status message deleted)

### v1.13.1 — Fix: image commands not deleting the processing message (Completed Jun 2026)
User reported that for `.img` / `.imgedit` (and `.style` / `.aged` / `.cartoon`) the initial "🎨 processing..." status message stayed behind after the image was sent.
- 🐛 **Root cause**: in `cmd_image`, `cmd_imgedit`, and `_do_image_transform`, `await msg.delete()` sat INSIDE the same `try/except` as `client.send_file(...)`. If the send succeeded but `delete()` raised (transient error / FloodWait / delete restriction), the shared `except` treated it as a send failure — re-edited the message to `img_send_failed` and left the processing message in place.
- ✅ **Fix**: moved `msg.delete()` OUT of the send `try/except` into its own guarded `try: ... except Exception: pass` block that runs only after a successful send; the send-failure `except` now carries an explicit `return`, and the `finally` still cleans the temp file. Now matches the pattern used by `.say` / `.up` / `.sc`.
- ✅ Verified by testing_agent: **184/184 tests pass** (+5 new regression tests in `TestImageProcessingMessageDeleted`: happy-path delete, delete-failure does not mislabel send, imgedit/transform delete, genuine send failure still reported).

### v1.13.0 — `.up` URL Uploader (Completed Jun 2026)
New feature: download a file from a direct link and re-upload it to Telegram, so the user doesn't have to download-then-forward manually.
- ✅ `.up <link>` — stream-download + upload; `reply + .up` auto-detects the link in the replied message (reuses `_extract_urls`)
- ✅ **Smart send**: images/videos/audio → media (`force_document=False`, video `supports_streaming=True`); everything else → document
- ✅ **Stylish caption card** under each file: 📄 Name · 🏷 Type (mime) · 💾 Size (human-readable) · 🌐 Source domain — bilingual
- ✅ Filename resolution: `Content-Disposition` (incl. `filename*=UTF-8''` percent-encoded, e.g. Persian names) → URL path → mime-based fallback; dangerous chars sanitized
- ✅ Streaming download in 1 MB chunks via `asyncio.to_thread` with live progress bar (10-segment) edited every 3s (download & upload)
- ✅ **2 GB size cap** enforced from `Content-Length` header AND during streaming
- ✅ Temp dir always cleaned up (`shutil.rmtree` in `finally`); uploader caption icons (📥🎬📄) added to `_BOT_MSG_PREFIXES` so the music auto-detect handler never re-processes them
- ✅ Helpers: `_download_url_file`, `_guess_upload_filename`, `_categorize_upload`, `_build_upload_caption`, `_human_size`, `_progress_bar`, `_safe_edit`
- ✅ Config: none (stateless). Help menu (en+fa) `📰 Web` section updated
- ✅ Tests: **179 passing** (+13 uploader tests) + real E2E (downloaded httpbin PNG → sent as media with correct caption)

### v1.12.0 — `.say` Text-to-Speech (Voice Messages) (Completed Jun 2026)
New feature: turn any text into a natural Telegram **voice message** via OpenAI TTS (Emergent Universal Key — no separate API key, no extra cost beyond key balance).
- ✅ `.say <text>` — generate & send a voice message; `reply + .say` speaks the replied message
- ✅ `.say -v onyx <text>` — per-message voice override flag
- ✅ `.voice` — view/list voices + model; `.voice <name>` sets default (9 voices); `.voice model tts-1|tts-1-hd` sets quality
- ✅ Output is **ogg-opus** (`response_format="opus"`, confirmed `OggS` container) → sent as a real Telegram voice note (`voice_note=True` + `DocumentAttributeAudio(voice=True)`), NO ffmpeg required
- ✅ Duration computed cheaply from the last Ogg page granule position (`_opus_duration`) — no ffprobe needed
- ✅ **Persian fully supported** (auto language detection) — live-verified with the real Emergent key (Persian → 13KB/3s ogg-opus, played as voice)
- ✅ Text >4096 chars auto-chunked on word boundaries into multiple sequential voice messages (OpenAI 4096 limit)
- ✅ Bilingual i18n for all new messages; help menu (en+fa) gets a `🔊 Voice` section; `.stats` shows voice+model
- ✅ New config keys: `tts_voice` (default `nova`), `tts_model` (default `tts-1-hd`)
- ✅ Helpers: `_tts_ready`, `_tts_generate`, `_extract_voice_flag`, `_chunk_text`, `_opus_duration`, `_friendly_tts_error`
- ✅ Tests: **166 passing** (+15 new TTS tests + real E2E generate + mocked full cmd_say pipeline verifying voice_note=True & OggS output)

### v1.11.3 — Full-Project Code Review & Bug-Fix Release (Completed Jun 2026)
User asked for a careful full-project review + fixes. 6 bugs fixed, all verified by testing agent (151/151 tests green):
- ✅ **GitHub `.tldr` parse bug**: `repo.rstrip(".git")` mangled repo names ending in t/i/g/. (`audit`→`aud`, `chat`→`cha`). New `_parse_github_repo()` helper strips only a real `.git` suffix.
- ✅ **Hang risk**: thumbnail download used `urllib.request.urlretrieve` (no timeout — could hang a music download forever). Now `urlopen(timeout=15)` + 5MB read cap.
- ✅ **Whitelist crash**: `_is_chat_allowed`/`_whitelist_contains`/`_whitelist_without` raised ValueError on hand-edited/garbage config entries. New `_to_int()` skips bad values gracefully.
- ✅ **Music auto-detect self-trigger**: `_BOT_MSG_PREFIXES` extended with 🔍🔒🎨🖼👴🧒📰🌐📦▶️📊📖 so the bot never re-downloads music links inside its own captions/summaries.
- ✅ **Log rotation**: `bidar.log` grew unbounded on VPS → `RotatingFileHandler` (5MB × 2 backups).
- ✅ **Dead code & stale docs**: removed unused `_sc_download_and_send`; `.env.example` no longer advertises a nonexistent `.update` Telegram command / `renderer.py` / unused `BIDAR_UPDATE_URL`.
- ✅ Tests: **129 passing** in project suite (+8 new: TestGithubRepoParse, TestWhitelistRobustness, TestBotMsgPrefixes) + 22 independent verification tests by testing agent (`tests/test_bug_fixes_verification.py`) = **151 total**.
- ✅ Verified healthy: `.help` text length (en 2941 / fa 2802 chars — under Telegram 4096 limit), systemd `Restart=always` covers `.restart`, i18n dict complete (every key has en+fa), install.sh/update.sh consistent.

### v1.10.0 — `.tldr` Link Summariser (Completed Jun 2026)
New command: AI-powered TL;DR for any URL — news articles, blog posts, GitHub repos, YouTube, generic web pages.
- ✅ `_extract_urls()` — regex extraction, dedup, balanced-parentheses aware (Wikipedia URLs like `Python_(programming_language)` survive intact)
- ✅ `_classify_url()` — github / youtube / generic routing
- ✅ `_fetch_page_text()` — fetches HTML, extracts `<title>`, `og:description`, `<article>`/`<main>` body, falls back to `<p>/<h1-3>/<li>` collection then full-body strip. Strips `<script>`/`<style>` first. Hard cap 800KB read, 6KB body sent to AI.
- ✅ `_fetch_github_repo()` — public GitHub API (no auth) for metadata + base64-decoded README.
- ✅ `_ai_summarise()` — one-shot summarisation reusing the configured chat model & Emergent key.
- ✅ Command modes:
  - `.tldr <url>` — direct
  - reply + `.tldr` — auto-detect URLs in replied message
- ✅ Up to **3 URLs** per call, summarised in parallel via `asyncio.gather`. Separator between chunks. >3900 chars splits into multiple replies (Telegram limit).
- ✅ Summary language is always **Persian (Farsi)** regardless of `bot_lang` (user preference).
- ✅ Friendly per-URL errors (timeout, paywall, non-HTML content type) instead of generic fail.
- ✅ Live verified: Wikipedia Python article (6KB body extracted), GitHub `torvalds/linux` (236k stars + README), URL extraction with balanced parens.
- ✅ Tests: **92 passing** (+11 new: URL extract incl. paren-balance, classify, strip_html, summarise wiring, GitHub flow, error path).
- ✅ Help menu updated (English & Persian) with `📰 Web` section.

### v1.9.5 — Real Image Errors Surfaced (Completed Jun 2026)
- ✅ `_generate_image` / `_edit_image` now return `(bytes, err)` tuples
- ✅ `_friendly_image_error()` maps Gemini errors → bilingual actionable messages (budget exceeded, safety filter, rate limit, invalid key, timeout)
- ✅ `.img` and `.imgedit` show the real reason; safety filter is the most common cause for detailed real-person + brand-name prompts
User reported: `.img` with a long detailed prompt (real-person + Mercedes brand) returned only generic "Image generation failed. Check: AI is on, EMERGENT_LLM_KEY is set, prompt is appropriate." — impossible to know whether it was budget, safety filter, rate limit, or invalid key.
- ✅ `_generate_image` / `_edit_image` now return `(bytes | None, error_msg | None)` instead of swallowing exceptions
- ✅ New `_friendly_image_error()` maps raw Gemini/litellm errors to actionable bilingual messages:
  - `Budget has been exceeded` → "💸 اعتبار Emergent Key تموم شده. از Profile → Universal Key شارژ کن"
  - safety / blocked / no images returned → "🛡 پرامپت توسط فیلتر امنیتی Gemini مسدود شد. برند رو حذف کن، توصیف چهره/سن/پوست واقعی نده"
  - rate limit → "⏳ محدودیت تعداد درخواست"
  - invalid key / 401 → "🔑 EMERGENT_LLM_KEY نامعتبره"
  - timeout → "⌛ Gemini پاسخ نداد"
  - otherwise → first 180 chars of the raw error
- ✅ `.img` and `.imgedit` now show the real reason; safety-filter is the most common cause for prompts with detailed real-person descriptions or trademarked brand names
- ✅ Tests: **81 passing** (+9 new for error mapping & generator error surfacing)

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
- User: "Save to GitHub" then `bash update.sh` on VPS to deploy v1.11.3
- User pick next feature from proposed list (35 proposals sent — voicetext/video/remind/summary top picks)

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
