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

    def test_youtube_url(self):
        for url in [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        ]:
            got = bidar._detect_music_url(f"listen: {url} now")
            self.assertIsNotNone(got, msg=f"Failed: {url}")
            self.assertEqual(got[0], "youtube", msg=url)
            self.assertFalse(got[2])

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
            "music_failed", "music_caption", "music_set",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
