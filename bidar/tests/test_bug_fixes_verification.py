"""Targeted verification of the 6 bug fixes reported by the main agent."""
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("PHONE", "x")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bidar  # noqa: E402


# -------- BUG FIX 1: _parse_github_repo --------
class TestGithubRepoParseEdgeCases:
    def test_repo_ending_in_t_preserved(self):
        assert bidar._parse_github_repo("https://github.com/user/audit") == ("user", "audit")

    def test_repo_ending_in_i_preserved(self):
        assert bidar._parse_github_repo("https://github.com/user/api") == ("user", "api")

    def test_repo_ending_in_g_preserved(self):
        assert bidar._parse_github_repo("https://github.com/user/tig") == ("user", "tig")

    def test_git_suffix_only_removed(self):
        assert bidar._parse_github_repo("https://github.com/user/repo.git") == ("user", "repo")
        assert bidar._parse_github_repo("https://github.com/user/tig.git") == ("user", "tig")

    def test_chat_repo_not_mangled(self):
        assert bidar._parse_github_repo("https://github.com/user/chat") == ("user", "chat")

    def test_non_github_returns_none(self):
        assert bidar._parse_github_repo("https://example.com/user/repo") is None

    def test_fetch_uses_parser(self):
        # Ensure _fetch_github_repo references _parse_github_repo
        import inspect
        src = inspect.getsource(bidar._fetch_github_repo)
        assert "_parse_github_repo" in src


# -------- BUG FIX 2: Whitelist robustness --------
class TestWhitelistRobustnessDeep:
    def test_garbage_entries_dont_crash_is_chat_allowed(self):
        bidar.config["allowed_groups"] = ["oops", None, "12.5", 42, "-1001234567890"]
        # Should not raise
        assert bidar._is_chat_allowed(42) is True
        assert bidar._is_chat_allowed(-1001234567890) is True
        assert bidar._is_chat_allowed(999) is False

    def test_whitelist_contains_mixed(self):
        wl = ["garbage", None, "12.5", "100", -1001234567890]
        assert bidar._whitelist_contains(100, wl) is True
        assert bidar._whitelist_contains(1234567890, wl) is True  # -100 form maps
        assert bidar._whitelist_contains(55, wl) is False

    def test_whitelist_without_removes_all_variants(self):
        wl = ["garbage", "-1001234567890", 1234567890, 42]
        result = bidar._whitelist_without(1234567890, wl)
        # Numeric variants of 1234567890 removed, garbage kept, 42 kept
        assert "garbage" in result
        assert 42 in result
        assert "-1001234567890" not in result
        assert 1234567890 not in result


# -------- BUG FIX 3: _BOT_MSG_PREFIXES extended --------
class TestBotMsgPrefixesExtended:
    def test_all_new_prefixes_present(self):
        prefixes = bidar._BOT_MSG_PREFIXES
        for p in ["🔍", "🔒", "🎨", "🖼", "👴", "🧒", "📰", "🌐", "📦", "▶️", "📊", "📖"]:
            assert any(x.startswith(p) or p in x for x in prefixes), f"Missing prefix: {p}"

    def test_tldr_message_matches(self):
        assert "📰 **TL;DR** of https://example.com".startswith(bidar._BOT_MSG_PREFIXES)

    def test_search_message_matches(self):
        assert "🔍 Search: python asyncio".startswith(bidar._BOT_MSG_PREFIXES)

    def test_image_gen_matches(self):
        assert "🎨 Generated image".startswith(bidar._BOT_MSG_PREFIXES)

    def test_owner_normal_music_url_not_excluded(self):
        # A normal owner message with just a music URL should NOT match prefixes
        assert not "https://music.youtube.com/watch?v=xyz".startswith(bidar._BOT_MSG_PREFIXES)
        assert not "check this out https://soundcloud.com/track".startswith(bidar._BOT_MSG_PREFIXES)


# -------- BUG FIX 5: log rotation --------
class TestLogRotation:
    def test_rotating_handler_in_source(self):
        """Verify RotatingFileHandler is set up in bidar module."""
        import logging.handlers
        import inspect
        src = inspect.getsource(bidar)
        assert "RotatingFileHandler" in src
        assert "import logging.handlers" in src
        # Ensure no legacy urlretrieve appears
        assert "urlretrieve" not in src


# -------- BUG FIX 6: dead code & version --------
class TestDeadCodeRemoved:
    def test_sc_download_and_send_absent(self):
        assert not hasattr(bidar, "_sc_download_and_send")

    def test_version_bumped(self):
        # Version must be >= 1.11.3 (semver-ish, monotonically increasing)
        parts = tuple(int(x) for x in bidar.VERSION.split("."))
        assert parts >= (1, 11, 3)


# -------- Regressions --------
class TestRegressionSpotChecks:
    def test_detect_music_url_only_music_youtube(self):
        assert bidar._detect_music_url("https://music.youtube.com/watch?v=abc") is not None
        assert bidar._detect_music_url("https://www.youtube.com/watch?v=abc") is None

    def test_parse_aspect_ratio_persian_story(self):
        assert bidar._parse_aspect_ratio("استوری") == "9:16"

    def test_is_persian_text(self):
        assert bidar._is_persian_text("سلام") is True
        assert bidar._is_persian_text("hello") is False

    def test_chat_id_variants(self):
        variants = bidar._chat_id_variants(-1001234567890)
        assert 1234567890 in variants
