"""
Test script for the SoundCloud download feature (.sc) in bidar.py.

Tests URL detection, argument routing, duration formatting, and the
search/download sync helpers with a mocked yt-dlp — no Telegram session
and no network required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Setup environment so bidar.py can be imported
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("PHONE", "x")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bidar  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def test_url_regex():
    print("\n── URL detection (_detect_music_url / soundcloud) ──")
    yes = [
        "https://soundcloud.com/artist/track",
        "http://soundcloud.com/a/b",
        "https://m.soundcloud.com/artist/track",
        "https://on.soundcloud.com/AbCdEf",
        "https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A873835351",
        "https://snd.sc/xyz",
        "check this https://soundcloud.com/x/y out",  # embedded in text
    ]
    no = [
        "shadmehr aghili setareh",
        "soundcloud.com/no-scheme",  # no scheme → treated as search query
        "2",
    ]
    for u in yes:
        got = bidar._detect_music_url(u)
        check(f"matches: {u[:60]}", got is not None and got[0] == "soundcloud")
    for u in no:
        check(f"no match: {u[:60]}", bidar._detect_music_url(u) is None)


def test_fmt_duration():
    print("\n── _fmt_duration ──")
    check("None → ?:??", bidar._fmt_duration(None) == "?:??")
    check("0 → ?:??", bidar._fmt_duration(0) == "?:??")
    check("59 → 0:59", bidar._fmt_duration(59) == "0:59")
    check("200.9 → 3:20", bidar._fmt_duration(200.9) == "3:20")
    check("3661 → 1:01:01", bidar._fmt_duration(3661) == "1:01:01")


def _fake_ydl(info):
    """Build a fake yt_dlp module whose YoutubeDL returns `info`."""
    fake = MagicMock()
    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = info
    fake.YoutubeDL.return_value.__enter__ = MagicMock(return_value=ydl_instance)
    fake.YoutubeDL.return_value.__exit__ = MagicMock(return_value=False)
    return fake, ydl_instance


def test_search_sync():
    print("\n── _sc_search_sync (mocked yt-dlp) ──")
    info = {"entries": [
        {"title": "Song A", "url": "https://api.soundcloud.com/tracks/1", "duration": 100, "uploader": "Artist1"},
        {"title": "Song B", "url": "https://api.soundcloud.com/tracks/2", "duration": 200, "uploader": None},
        None,  # dead entry must be skipped
        {"title": None, "url": "https://api.soundcloud.com/tracks/3", "duration": None, "uploader": "X"},
        {"title": "No URL", "url": None},  # skipped: no url
    ]}
    fake, ydl = _fake_ydl(info)
    with patch.object(bidar, "yt_dlp", fake):
        results = bidar._sc_search_sync("test query")
    check("query passed as scsearch5:", ydl.extract_info.call_args[0][0] == "scsearch5:test query")
    check("3 valid results", len(results) == 3, f"got {len(results)}")
    check("title kept", results[0]["title"] == "Song A")
    check("missing uploader → ''", results[1]["uploader"] == "")
    check("missing title → Unknown", results[2]["title"] == "Unknown")


def test_download_sync(tmpdir_base="/tmp/bidar_sc_unittest"):
    print("\n── _music_download_sync (mocked yt-dlp) ──")
    import shutil as _sh
    _sh.rmtree(tmpdir_base, ignore_errors=True)
    os.makedirs(tmpdir_base)
    # Simulate yt-dlp writing an audio file into tmpdir
    audio_file = os.path.join(tmpdir_base, "My Song.mp3")
    info = {"title": "My Song", "uploader": "DJ Test", "duration": 181.4, "thumbnail": ""}

    fake, ydl = _fake_ydl(info)

    def write_file(*a, **k):
        with open(audio_file, "wb") as f:
            f.write(b"ID3fakemp3")
        return info

    ydl.extract_info.side_effect = write_file
    with patch.object(bidar, "yt_dlp", fake):
        out = bidar._music_download_sync("https://soundcloud.com/x/y", tmpdir_base)
    check("returns dict", out is not None)
    check("filepath found", out and out["filepath"] == audio_file)
    check("duration int", out and out["duration"] == 181)
    check("no thumb (empty url)", out and out["thumb"] is None)

    # entries-wrapped result (e.g., a set/playlist) → first entry used
    fake2, ydl2 = _fake_ydl({"entries": [info]})
    ydl2.extract_info.side_effect = write_file
    with patch.object(bidar, "yt_dlp", fake2):
        out2 = bidar._music_download_sync("https://soundcloud.com/x/sets/y", tmpdir_base)
    check("playlist → first entry", out2 is not None and out2["title"] == "My Song")

    # no audio file produced → None
    _sh.rmtree(tmpdir_base, ignore_errors=True)
    os.makedirs(tmpdir_base)
    fake3, ydl3 = _fake_ydl(info)  # extract_info returns info but writes nothing
    with patch.object(bidar, "yt_dlp", fake3):
        out3 = bidar._music_download_sync("https://soundcloud.com/x/y", tmpdir_base)
    check("no file → None", out3 is None)
    _sh.rmtree(tmpdir_base, ignore_errors=True)


def test_arg_routing():
    print("\n── .sc argument routing ──")
    # mirrors cmd_soundcloud routing rules
    def route(arg: str) -> str:
        arg = arg.strip()
        if arg.isdigit():
            return "pick"
        if bidar._detect_music_url(arg):
            return "link"
        return "search"

    check("'2' → pick", route("2") == "pick")
    check("'10' → pick", route("10") == "pick")
    check("link → link", route("https://soundcloud.com/a/b") == "link")
    check("name → search", route("shadmehr setareh") == "search")
    check("name with digits → search", route("song 2023 remix") == "search")


def test_results_state():
    print("\n── per-chat results state ──")
    bidar._sc_results.clear()
    bidar._sc_results[111] = [{"title": "A", "url": "u1"}]
    bidar._sc_results[222] = [{"title": "B", "url": "u2"}]
    check("chat 111 isolated", bidar._sc_results[111][0]["title"] == "A")
    check("chat 222 isolated", bidar._sc_results[222][0]["title"] == "B")
    check("unknown chat → None", bidar._sc_results.get(333) is None)


def test_i18n_keys():
    print("\n── i18n keys (en + fa present) ──")
    # Legacy sc_ keys that remain (search-related)
    legacy_keys = ["sc_usage", "sc_lib_missing", "sc_searching", "sc_no_results",
                   "sc_results", "sc_no_pending", "sc_invalid_pick"]
    # New universal music keys
    music_keys = ["music_downloading", "music_uploading", "music_failed", "music_caption"]
    for k in legacy_keys + music_keys:
        entry = bidar.I18N.get(k, {})
        check(k, bool(entry.get("en")) and bool(entry.get("fa")))
    # help mentions .sc in both languages
    check("help en mentions sc", "}sc <" in bidar.I18N["help_full"]["en"])
    check("help fa mentions sc", "}sc <" in bidar.I18N["help_full"]["fa"])


if __name__ == "__main__":
    test_url_regex()
    test_fmt_duration()
    test_search_sync()
    test_download_sync()
    test_arg_routing()
    test_results_state()
    test_i18n_keys()
    print(f"\n{'='*40}\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
