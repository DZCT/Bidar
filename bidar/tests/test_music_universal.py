"""
Tests for the Universal Music Downloader + Allow whitelist + auto-detect.
Runs without a live Telegram session — uses mocks only.

Run:
    cd /app/bidar && python tests/test_music_universal.py
"""
from __future__ import annotations

import os
import sys
import copy
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Stub env vars BEFORE importing bidar (which reads them at import time)
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("PHONE", "x")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bidar  # noqa: E402


# ────────────────────────────────────────────────────────────────────
# 1. URL Detection
# ────────────────────────────────────────────────────────────────────
class TestUrlDetection(unittest.TestCase):
    def test_soundcloud_url(self):
        got = bidar._detect_music_url("Check https://soundcloud.com/artist/song-title cool")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "soundcloud")
        self.assertFalse(got[2])

    def test_youtube_music_only(self):
        """Only music.youtube.com is treated as music — regular video links are ignored."""
        # Music: detected as YouTube Music
        got = bidar._detect_music_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "youtube")
        got = bidar._detect_music_url("https://music.youtube.com/playlist?list=PLabc123")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "youtube")
        # Regular YouTube video / short links must NOT be auto-handled
        for url in [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/shorts/abc",
        ]:
            self.assertIsNone(bidar._detect_music_url(url), msg=f"should be ignored: {url}")

    def test_spotify_url(self):
        got = bidar._detect_music_url(
            "track https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC enjoy"
        )
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "spotify")
        self.assertTrue(got[2])

    def test_spotify_intl_url(self):
        got = bidar._detect_music_url(
            "https://open.spotify.com/intl-fa/track/4uLU6hMCjMI75M1A2tKUQC"
        )
        self.assertEqual(got[0], "spotify")

    def test_deezer_url(self):
        got = bidar._detect_music_url("https://www.deezer.com/track/123456789")
        self.assertEqual(got[0], "deezer")
        self.assertTrue(got[2])

    def test_apple_music_url(self):
        got = bidar._detect_music_url(
            "https://music.apple.com/us/song/blinding-lights/1499378108"
        )
        self.assertEqual(got[0], "apple")
        self.assertTrue(got[2])

    def test_tidal_url(self):
        got = bidar._detect_music_url("https://tidal.com/browse/track/12345")
        self.assertEqual(got[0], "tidal")
        self.assertTrue(got[2])

    def test_bandcamp_url(self):
        got = bidar._detect_music_url("https://artist.bandcamp.com/track/song-name")
        self.assertEqual(got[0], "bandcamp")
        self.assertFalse(got[2])

    def test_mixcloud_url(self):
        got = bidar._detect_music_url("https://www.mixcloud.com/user/track-name/")
        self.assertEqual(got[0], "mixcloud")

    def test_no_music_url(self):
        for noise in [
            "",
            "just a normal message",
            "https://google.com",
            "https://twitter.com/foo",
            "https://example.com/song",
            "soundcloud is great",  # text mention only, no URL
        ]:
            self.assertIsNone(
                bidar._detect_music_url(noise),
                msg=f"False positive for: {noise!r}",
            )


# ────────────────────────────────────────────────────────────────────
# 2. DRM Metadata extraction (mock urllib.request)
# ────────────────────────────────────────────────────────────────────
class TestDrmMetadata(unittest.TestCase):
    def _mock_resp(self, html: str):
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda *a: None
        m.read.return_value = html.encode("utf-8")
        return m

    def test_spotify(self):
        html = (
            '<meta property="og:title" content="Blinding Lights">'
            '<meta property="og:description" '
            'content="Listen to Blinding Lights on Spotify. The Weeknd · Song · 2019">'
        )
        with patch("urllib.request.urlopen", return_value=self._mock_resp(html)):
            q = bidar._fetch_drm_metadata("https://open.spotify.com/track/abc", "spotify")
        self.assertIsNotNone(q)
        self.assertIn("Blinding Lights", q)
        self.assertIn("The Weeknd", q)

    def test_deezer(self):
        html = (
            '<meta property="og:title" content="Shape of You">'
            '<meta property="og:description" content="Listen to Shape of You by Ed Sheeran on Deezer">'
        )
        with patch("urllib.request.urlopen", return_value=self._mock_resp(html)):
            q = bidar._fetch_drm_metadata("https://deezer.com/track/1", "deezer")
        self.assertIn("Shape of You", q)
        self.assertIn("Ed Sheeran", q)

    def test_apple(self):
        html = (
            '<meta property="og:title" content="Bohemian Rhapsody">'
            '<meta property="og:description" content="Song · Queen · 1975">'
        )
        with patch("urllib.request.urlopen", return_value=self._mock_resp(html)):
            q = bidar._fetch_drm_metadata(
                "https://music.apple.com/us/song/bohemian-rhapsody/1", "apple"
            )
        self.assertIn("Bohemian Rhapsody", q)
        self.assertIn("Queen", q)

    def test_no_metadata(self):
        with patch("urllib.request.urlopen", return_value=self._mock_resp("<html></html>")):
            q = bidar._fetch_drm_metadata("https://open.spotify.com/track/x", "spotify")
        self.assertIsNone(q)

    def test_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network")):
            q = bidar._fetch_drm_metadata("https://open.spotify.com/track/x", "spotify")
        self.assertIsNone(q)


# ────────────────────────────────────────────────────────────────────
# 3. Allow whitelist
# ────────────────────────────────────────────────────────────────────
class TestAllowList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bidar_test_")
        bidar.CONFIG_FILE = Path(self.tmpdir) / "bidar_config.json"
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.save_config()

    def test_default_is_empty(self):
        self.assertEqual(bidar.config["allowed_groups"], [])

    def test_add_and_persist(self):
        bidar.config["allowed_groups"].append(-100123)
        bidar.save_config()
        bidar.load_config()
        self.assertIn(-100123, bidar.config["allowed_groups"])

    def test_music_enabled_default(self):
        self.assertTrue(bidar.config["music_enabled"])


# ────────────────────────────────────────────────────────────────────
# 4. End-to-end auto-detect flow
# ────────────────────────────────────────────────────────────────────
class TestAutoDetectFlow(unittest.IsolatedAsyncioTestCase):
    def _mk_event(self, *, text, chat_id, is_private):
        ev = MagicMock()
        ev.raw_text = text
        ev.chat_id = chat_id
        ev.is_private = is_private
        ev.message = MagicMock()
        ev.message.id = 42
        return ev

    async def test_pv_always_allowed(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.config["allowed_groups"] = []
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()

        called = {}

        async def fake_dl(event, url, platform, is_drm, **kw):
            called["platform"] = platform
            called["is_drm"] = is_drm
            called["url"] = url

        ev = self._mk_event(
            text="Check https://open.spotify.com/track/abc",
            chat_id=999, is_private=True,
        )
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
        self.assertEqual(called.get("platform"), "spotify")
        self.assertTrue(called.get("is_drm"))

    async def test_group_not_whitelisted_skipped(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.config["allowed_groups"] = [12345]
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        called = {"n": 0}

        async def fake_dl(*a, **kw):
            called["n"] += 1

        ev = self._mk_event(
            text="https://soundcloud.com/foo/bar",
            chat_id=-100999, is_private=False,
        )
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
        self.assertEqual(called["n"], 0)

    async def test_group_whitelisted_allowed(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.config["allowed_groups"] = [-100999]
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        called = {"url": None}

        async def fake_dl(event, url, platform, is_drm, **kw):
            called["url"] = url

        ev = self._mk_event(
            text="https://soundcloud.com/foo/bar",
            chat_id=-100999, is_private=False,
        )
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
        self.assertIn("soundcloud.com/foo/bar", called["url"] or "")

    async def test_music_disabled_skips(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = False
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        called = {"n": 0}

        async def fake_dl(*a, **kw):
            called["n"] += 1

        ev = self._mk_event(
            text="https://open.spotify.com/track/abc",
            chat_id=999, is_private=True,
        )
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
        self.assertEqual(called["n"], 0)

    async def test_dedup_within_5min(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        count = {"n": 0}

        async def fake_dl(*a, **kw):
            count["n"] += 1
            return True  # success keeps the dedup entry

        ev = self._mk_event(
            text="https://open.spotify.com/track/dedupe",
            chat_id=9876, is_private=True,
        )
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
            await bidar._maybe_handle_music_link(ev, sender)  # immediate retry
        self.assertEqual(count["n"], 1)


# ────────────────────────────────────────────────────────────────────
# 5. i18n: ensure all new keys are present for both languages
# ────────────────────────────────────────────────────────────────────
class TestI18N(unittest.TestCase):
    def test_new_keys_present(self):
        keys = [
            "music_downloading", "music_resolving", "music_uploading",
            "music_failed", "music_meta_failed", "music_caption", "music_set",
            "allow_help", "allow_added", "allow_exists", "allow_removed",
            "allow_notfound", "allow_invalid", "allow_list_empty",
            "allow_list_title", "allow_cleared", "allow_here_pv",
        ]
        for k in keys:
            entry = bidar.I18N.get(k, {})
            self.assertTrue(entry.get("en"), msg=f"missing en for {k}")
            self.assertTrue(entry.get("fa"), msg=f"missing fa for {k}")

    def test_help_mentions_new_commands(self):
        en = bidar.I18N["help_full"]["en"]
        fa = bidar.I18N["help_full"]["fa"]
        self.assertIn("music on|off", en)
        self.assertIn("allow help", en)
        self.assertIn("music on|off", fa)
        self.assertIn("allow help", fa)


# ────────────────────────────────────────────────────────────────────
# 6. v1.9.1 fixes: shortlinks, chat-ID variants, outgoing links, dedup retry
# ────────────────────────────────────────────────────────────────────
class TestShortlinkDetection(unittest.TestCase):
    def test_on_soundcloud_shortlink_detected(self):
        got = bidar._detect_music_url("https://on.soundcloud.com/aquUJPmourEr5c6Lul")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "soundcloud")
        self.assertFalse(got[2])

    def test_spotify_link_short_detected_as_drm(self):
        got = bidar._detect_music_url("listen https://spotify.link/AbC123xyz now")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "spotify")
        self.assertTrue(got[2])

    def test_deezer_page_link_detected_as_drm(self):
        got = bidar._detect_music_url("https://deezer.page.link/XyZ987")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "deezer")
        self.assertTrue(got[2])

    def test_shortlink_re_matches_only_drm_shorteners(self):
        self.assertTrue(bidar._SHORTLINK_RE.match("https://spotify.link/abc"))
        self.assertTrue(bidar._SHORTLINK_RE.match("https://deezer.page.link/x"))
        self.assertIsNone(bidar._SHORTLINK_RE.match("https://on.soundcloud.com/x"))
        self.assertIsNone(bidar._SHORTLINK_RE.match("https://open.spotify.com/track/x"))


class TestChatIdVariants(unittest.TestCase):
    def test_marked_supergroup_includes_raw(self):
        v = bidar._chat_id_variants(-1002453861964)
        self.assertIn(2453861964, v)
        self.assertIn(-1002453861964, v)

    def test_raw_positive_includes_marked(self):
        v = bidar._chat_id_variants(2453861964)
        self.assertIn(-1002453861964, v)

    def test_legacy_group_includes_positive(self):
        v = bidar._chat_id_variants(-456789)
        self.assertIn(456789, v)
        self.assertIn(-100456789, v)

    def test_invalid_returns_empty(self):
        self.assertEqual(bidar._chat_id_variants("abc"), set())

    def test_is_chat_allowed_raw_id_matches_marked_chat(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["allowed_groups"] = [2453861964]  # raw `.id`-style entry
        self.assertTrue(bidar._is_chat_allowed(-1002453861964))

    def test_is_chat_allowed_marked_entry_matches(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["allowed_groups"] = [-1002453861964]
        self.assertTrue(bidar._is_chat_allowed(-1002453861964))

    def test_is_chat_allowed_rejects_other_chat(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["allowed_groups"] = [111222333]
        self.assertFalse(bidar._is_chat_allowed(-1009998887776))

    def test_whitelist_contains_and_without(self):
        lst = [2453861964, -100555]
        self.assertTrue(bidar._whitelist_contains(-1002453861964, lst))
        remaining = bidar._whitelist_without(-1002453861964, lst)
        self.assertEqual(remaining, [-100555])


class TestAutoDetectV191(unittest.IsolatedAsyncioTestCase):
    def _mk_event(self, *, text, chat_id, is_private):
        ev = MagicMock()
        ev.raw_text = text
        ev.chat_id = chat_id
        ev.is_private = is_private
        ev.message = MagicMock()
        ev.message.id = 42
        return ev

    async def test_group_raw_id_whitelist_triggers(self):
        """Group stored with raw positive `.id` output must still trigger."""
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.config["allowed_groups"] = [2453861964]
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        called = {"n": 0}

        async def fake_dl(*a, **kw):
            called["n"] += 1
            return True

        ev = self._mk_event(text="https://soundcloud.com/foo/bar",
                            chat_id=-1002453861964, is_private=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, MagicMock(id=1, bot=False))
        self.assertEqual(called["n"], 1)

    async def test_outgoing_owner_message_sender_none(self):
        """Owner's own (outgoing) link → sender=None must still work in PV."""
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        called = {"kw": None}

        async def fake_dl(event, url, platform, is_drm, **kw):
            called["kw"] = kw
            return True

        ev = self._mk_event(text="https://on.soundcloud.com/abc123",
                            chat_id=555, is_private=True)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, None)
        self.assertIsNotNone(called["kw"])
        self.assertTrue(called["kw"].get("force_reply"))

    async def test_failed_download_clears_dedup_for_retry(self):
        """A failed download must NOT block an immediate retry of the same link."""
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["music_enabled"] = True
        bidar.YTDLP_OK = True
        bidar._music_recent.clear()
        count = {"n": 0}

        async def fake_dl(*a, **kw):
            count["n"] += 1
            return False  # simulate failure

        ev = self._mk_event(text="https://soundcloud.com/retry/me",
                            chat_id=777, is_private=True)
        sender = MagicMock(id=111, bot=False)
        with patch.object(bidar, "_music_download_and_send", side_effect=fake_dl):
            await bidar._maybe_handle_music_link(ev, sender)
            await bidar._maybe_handle_music_link(ev, sender)  # retry after failure
        self.assertEqual(count["n"], 2)


# ────────────────────────────────────────────────────────────────────
# 7. v1.9.2: metadata APIs (iTunes/Deezer), query cleaner, YT oEmbed fallback
# ────────────────────────────────────────────────────────────────────
class TestCleanQuery(unittest.TestCase):
    def test_unescape_and_nbsp(self):
        self.assertEqual(bidar._clean_query("Let&#39;s Go on Apple\xa0Music"),
                         "Let's Go on Apple Music")

    def test_strips_official_video(self):
        self.assertEqual(bidar._clean_query("Artist - Song (Official Video)"), "Artist - Song")
        self.assertEqual(bidar._clean_query("Artist - Song [Official Lyric Video]"), "Artist - Song")

    def test_strips_single_suffix(self):
        self.assertEqual(bidar._clean_query("The Weeknd - Blinding Lights - Single"),
                         "The Weeknd - Blinding Lights")


class TestPlatformLookups(unittest.TestCase):
    def test_apple_lookup_uses_i_param(self):
        calls = []

        def fake_json(url, timeout=15):
            calls.append(url)
            return {"results": [{"artistName": "Joost", "trackName": "Europapa"}]}

        with patch.object(bidar, "_http_json", side_effect=fake_json):
            q = bidar._apple_lookup("https://music.apple.com/us/album/europapa/1732041797?i=1732041802")
        self.assertEqual(q, "Joost - Europapa")
        self.assertIn("id=1732041802", calls[0])
        self.assertIn("country=us", calls[0])

    def test_apple_lookup_song_path_id(self):
        def fake_json(url, timeout=15):
            return {"results": [{"artistName": "Joost", "trackName": "Europapa"}]}

        with patch.object(bidar, "_http_json", side_effect=fake_json):
            q = bidar._apple_lookup("https://music.apple.com/us/song/europapa/1732041802")
        self.assertEqual(q, "Joost - Europapa")

    def test_apple_lookup_dead_link_returns_none(self):
        with patch.object(bidar, "_http_json", return_value={"resultCount": 0, "results": []}):
            q = bidar._apple_lookup("https://music.apple.com/us/album/x/1499385311?i=1499385316")
        self.assertIsNone(q)

    def test_deezer_lookup(self):
        def fake_json(url, timeout=15):
            assert "api.deezer.com/track/3135556" in url
            return {"title": "Harder, Better, Faster, Stronger", "artist": {"name": "Daft Punk"}}

        with patch.object(bidar, "_http_json", side_effect=fake_json):
            q = bidar._deezer_lookup("https://www.deezer.com/track/3135556")
        self.assertEqual(q, "Daft Punk - Harder, Better, Faster, Stronger")

    def test_youtube_title_query_strips_topic(self):
        with patch.object(bidar, "_http_json",
                          return_value={"title": "Barbie (Remix)", "author_name": "JaidynAlexis - Topic"}):
            q = bidar._youtube_title_query("https://music.youtube.com/watch?v=x")
        self.assertEqual(q, "JaidynAlexis - Barbie (Remix)")

    def test_youtube_title_author_already_in_title(self):
        with patch.object(bidar, "_http_json",
                          return_value={"title": "Joost - Europapa", "author_name": "Joost"}):
            q = bidar._youtube_title_query("https://youtu.be/x")
        self.assertEqual(q, "Joost - Europapa")

    def test_fetch_drm_uses_apple_api_first(self):
        with patch.object(bidar, "_apple_lookup", return_value="Joost - Europapa") as al:
            q = bidar._fetch_drm_metadata("https://music.apple.com/us/song/europapa/1732041802", "apple")
        self.assertEqual(q, "Joost - Europapa")
        al.assert_called_once()


class TestDownloadSyncVideoFallback(unittest.TestCase):
    def test_mp4_used_when_no_audio_file(self):
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        try:
            with open(os.path.join(tmp, "Song.mp4"), "wb") as f:
                f.write(b"0" * 100)
            fake = MagicMock()
            ydl = MagicMock()
            ydl.extract_info.return_value = {"title": "Song", "uploader": "X",
                                             "duration": 100, "thumbnail": ""}
            fake.YoutubeDL.return_value.__enter__ = MagicMock(return_value=ydl)
            fake.YoutubeDL.return_value.__exit__ = MagicMock(return_value=False)
            with patch.object(bidar, "yt_dlp", fake):
                out = bidar._music_download_sync("https://youtube.com/watch?v=x", tmp)
            self.assertIsNotNone(out)
            self.assertTrue(out["filepath"].endswith(".mp4"))
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def test_part_files_ignored(self):
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        try:
            with open(os.path.join(tmp, "Song.mp3.part"), "wb") as f:
                f.write(b"0" * 100)
            fake = MagicMock()
            ydl = MagicMock()
            ydl.extract_info.return_value = {"title": "Song"}
            fake.YoutubeDL.return_value.__enter__ = MagicMock(return_value=ydl)
            fake.YoutubeDL.return_value.__exit__ = MagicMock(return_value=False)
            with patch.object(bidar, "yt_dlp", fake):
                out = bidar._music_download_sync("https://soundcloud.com/x/y", tmp)
            self.assertIsNone(out)
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)


# ────────────────────────────────────────────────────────────────────
# 8. v1.9.4: image aspect-ratio helpers
# ────────────────────────────────────────────────────────────────────
class TestAspectRatio(unittest.TestCase):
    def test_canonical_ratios(self):
        for ar in ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9",
                   "3:2", "2:3", "5:4", "4:5", "1:4", "4:1", "1:8", "8:1"):
            self.assertEqual(bidar._parse_aspect_ratio(ar), ar, ar)

    def test_english_aliases(self):
        self.assertEqual(bidar._parse_aspect_ratio("square"), "1:1")
        self.assertEqual(bidar._parse_aspect_ratio("LANDSCAPE"), "16:9")
        self.assertEqual(bidar._parse_aspect_ratio("portrait"), "9:16")
        self.assertEqual(bidar._parse_aspect_ratio("story"), "9:16")
        self.assertEqual(bidar._parse_aspect_ratio("cinematic"), "21:9")
        self.assertEqual(bidar._parse_aspect_ratio("photo"), "3:2")
        self.assertEqual(bidar._parse_aspect_ratio("tv"), "4:3")

    def test_persian_aliases(self):
        self.assertEqual(bidar._parse_aspect_ratio("مربعی"), "1:1")
        self.assertEqual(bidar._parse_aspect_ratio("افقی"), "16:9")
        self.assertEqual(bidar._parse_aspect_ratio("عمودی"), "9:16")
        self.assertEqual(bidar._parse_aspect_ratio("استوری"), "9:16")
        self.assertEqual(bidar._parse_aspect_ratio("سینمایی"), "21:9")
        self.assertEqual(bidar._parse_aspect_ratio("عکس"), "3:2")

    def test_tolerant_separators(self):
        self.assertEqual(bidar._parse_aspect_ratio("16x9"), "16:9")
        self.assertEqual(bidar._parse_aspect_ratio("16X9"), "16:9")
        self.assertEqual(bidar._parse_aspect_ratio("16×9"), "16:9")
        self.assertEqual(bidar._parse_aspect_ratio(" 9 / 16 "), "9:16")

    def test_invalid(self):
        self.assertIsNone(bidar._parse_aspect_ratio(""))
        self.assertIsNone(bidar._parse_aspect_ratio(None))
        self.assertIsNone(bidar._parse_aspect_ratio("100:1"))
        self.assertIsNone(bidar._parse_aspect_ratio("garbage"))
        self.assertIsNone(bidar._parse_aspect_ratio("0:0"))
        # `4:5` IS supported by Gemini
        self.assertEqual(bidar._parse_aspect_ratio("4:5"), "4:5")

    def test_extract_flag_ar(self):
        ar, p = bidar._extract_ar_flag("--ar 16:9 a red apple on white")
        self.assertEqual(ar, "16:9")
        self.assertEqual(p, "a red apple on white")

    def test_extract_flag_shorthand(self):
        ar, p = bidar._extract_ar_flag("a moody portrait --9:16")
        self.assertEqual(ar, "9:16")
        self.assertEqual(p, "a moody portrait")

    def test_extract_flag_alias(self):
        ar, p = bidar._extract_ar_flag("--landscape sunset over mountains")
        self.assertEqual(ar, "16:9")
        self.assertEqual(p, "sunset over mountains")

    def test_extract_flag_persian_alias(self):
        ar, p = bidar._extract_ar_flag("--استوری یه نقاشی مینیمال از کوه")
        self.assertEqual(ar, "9:16")
        self.assertEqual(p, "یه نقاشی مینیمال از کوه")

    def test_extract_no_flag(self):
        ar, p = bidar._extract_ar_flag("a red apple on white")
        self.assertIsNone(ar)
        self.assertEqual(p, "a red apple on white")

    def test_default_in_config(self):
        self.assertEqual(bidar._DEFAULT_CONFIG["image_aspect_ratio"], "1:1")


class TestGenerateImagePassesAR(unittest.IsolatedAsyncioTestCase):
    async def test_uses_config_default(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["image_aspect_ratio"] = "16:9"
        bidar.config["ai_enabled"] = True
        # Capture the with_params call
        captured = {}

        class FakeChat:
            def with_model(self, *a, **kw): return self
            def with_params(self, **kw):
                captured.update(kw)
                return self
            async def send_message_multimodal_response(self, *a, **kw):
                return ("", [{"data": __import__("base64").b64encode(b"PNGdata").decode()}])

        with patch.object(bidar, "_ai_ready", return_value=(True, "")), \
             patch.object(bidar, "LlmChat", return_value=FakeChat()):
            out = await bidar._generate_image("a cat")
        self.assertIsNotNone(out)
        self.assertEqual(captured.get("image_config"), {"aspect_ratio": "16:9"})

    async def test_explicit_override_wins(self):
        bidar.config = copy.deepcopy(bidar._DEFAULT_CONFIG)
        bidar.config["image_aspect_ratio"] = "1:1"
        bidar.config["ai_enabled"] = True
        captured = {}

        class FakeChat:
            def with_model(self, *a, **kw): return self
            def with_params(self, **kw):
                captured.update(kw)
                return self
            async def send_message_multimodal_response(self, *a, **kw):
                return ("", [{"data": __import__("base64").b64encode(b"PNG").decode()}])

        with patch.object(bidar, "_ai_ready", return_value=(True, "")), \
             patch.object(bidar, "LlmChat", return_value=FakeChat()):
            await bidar._generate_image("a dog", aspect_ratio="9:16")
        self.assertEqual(captured.get("image_config"), {"aspect_ratio": "9:16"})


if __name__ == "__main__":
    unittest.main(verbosity=2)