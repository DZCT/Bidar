"""
Test script for the search feature in bidar.py.

Tests the search logic without requiring a real Telegram session by mocking the
client and entities.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Setup environment so bidar.py can be imported
os.environ.setdefault("API_ID", "0")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("PHONE", "x")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_dialog(name: str, dialog_id: int, *, is_user=False, is_group=False,
                 is_bot=False, restricted=False, messages=None):
    """Create a mock Telethon dialog object."""
    entity = SimpleNamespace(bot=is_bot, restricted=restricted)
    dialog = SimpleNamespace(
        name=name,
        id=dialog_id,
        entity=entity,
        is_user=is_user,
        is_group=is_group,
        is_channel=not (is_user or is_group),
    )
    dialog._messages = messages or []
    return dialog


def _make_message(msg_id: int, text: str, sender_id: int = 1):
    """Create a mock message."""
    return SimpleNamespace(
        id=msg_id,
        text=text,
        message=text,
        date=datetime(2026, 2, 13, 12, 0, 0),
        sender_id=sender_id,
    )


async def _run_tests():
    # Build a fake client with iter_dialogs and iter_messages
    fake_dialogs = [
        _make_dialog("Alice (private)", 100, is_user=True, messages=[
            _make_message(1, "hello ali, how are you?"),
            _make_message(2, "let's meet tomorrow"),
        ]),
        _make_dialog("BotChat", 200, is_user=True, is_bot=True, messages=[
            _make_message(3, "ali bot response"),
        ]),
        _make_dialog("Public Group", 300, is_group=True, messages=[
            _make_message(4, "hi ali!"),
        ]),
        _make_dialog("Public Channel", 400, messages=[
            _make_message(5, "ali post"),
        ]),
        _make_dialog("Banned Channel", 500, restricted=True, messages=[
            _make_message(6, "blocked post about ali"),
            _make_message(7, "another blocked ali message"),
        ]),
        _make_dialog("Restricted Group", 600, is_group=True, restricted=True,
                     messages=[_make_message(8, "restricted ali talk")]),
    ]

    async def fake_iter_dialogs():
        for d in fake_dialogs:
            yield d

    async def fake_iter_messages(entity, search=None, limit=100):
        # Find the dialog matching this entity
        for d in fake_dialogs:
            if d.entity is entity:
                for m in d._messages:
                    if search is None or search.lower() in m.text.lower():
                        yield m
                return

    # Import after path setup
    import bidar  # noqa: E402

    # Patch the global client
    fake_client = MagicMock()
    fake_client.iter_dialogs = fake_iter_dialogs
    fake_client.iter_messages = fake_iter_messages
    bidar.client = fake_client

    # ─── Test 1: .search (normal mode) ───
    print("TEST 1: .search 'ali' (only normal chats, skip restricted + bots)")
    results, total, searched, skipped, errors = await bidar._search_all_chats(
        "ali", only_restricted=False
    )
    print(f"  total={total} searched={searched} skipped={skipped} errors={len(errors)}")
    print(f"  matches in chats: {[r['name'] for r in results]}")
    assert total == 6, f"Expected 6 total dialogs, got {total}"
    # searched: Alice, Public Group, Public Channel (3); skipped: BotChat, Banned, Restricted (3)
    assert searched == 3, f"Expected 3 searched, got {searched}"
    assert skipped == 3, f"Expected 3 skipped, got {skipped}"
    chat_names = {r["name"] for r in results}
    assert chat_names == {"Alice (private)", "Public Group", "Public Channel"}, \
        f"Unexpected chat names: {chat_names}"
    assert not any(r["restricted"] for r in results), \
        "Normal search must NOT include restricted chats"
    print("  ✓ PASS")

    # ─── Test 2: .searchall (restricted only) ───
    print("\nTEST 2: .searchall 'ali' (only restricted/blocked)")
    results, total, searched, skipped, errors = await bidar._search_all_chats(
        "ali", only_restricted=True
    )
    print(f"  total={total} searched={searched} skipped={skipped} errors={len(errors)}")
    print(f"  matches in chats: {[r['name'] for r in results]}")
    assert total == 6
    # Only Banned Channel + Restricted Group searched (2)
    assert searched == 2, f"Expected 2 searched (restricted only), got {searched}"
    assert skipped == 4, f"Expected 4 skipped, got {skipped}"
    chat_names = {r["name"] for r in results}
    assert chat_names == {"Banned Channel", "Restricted Group"}, \
        f"Unexpected: {chat_names}"
    assert all(r["restricted"] for r in results), \
        ".searchall results must ALL be restricted"
    print("  ✓ PASS")

    # ─── Test 3: Report formatting ───
    print("\nTEST 3: Report formatting (only_restricted=True)")
    report = bidar._format_search_report(
        "ali", results, total, searched, skipped, errors,
        only_restricted=True,
    )
    assert "Restricted/Blocked channels ONLY" in report
    assert "🔒RESTRICTED" in report
    assert "Banned Channel" in report
    assert "Restricted Group" in report
    print("  ✓ PASS (report length: %d chars)" % len(report))

    # ─── Test 4: Report formatting normal mode ───
    print("\nTEST 4: Report formatting (only_restricted=False)")
    results_normal, total_n, searched_n, skipped_n, errors_n = (
        await bidar._search_all_chats("ali", only_restricted=False)
    )
    report_n = bidar._format_search_report(
        "ali", results_normal, total_n, searched_n, skipped_n, errors_n,
        only_restricted=False,
    )
    assert "Normal chats only" in report_n
    assert "🔒RESTRICTED" not in report_n
    print("  ✓ PASS")

    # ─── Test 5: i18n keys exist ───
    print("\nTEST 5: All i18n keys for search exist")
    required_keys = [
        "search_usage", "search_too_short", "search_starting",
        "search_starting_restricted", "search_progress", "search_no_results",
        "search_no_restricted", "search_caption", "search_caption_restricted",
    ]
    for key in required_keys:
        assert key in bidar.I18N, f"Missing i18n key: {key}"
        assert "en" in bidar.I18N[key], f"Missing 'en' for {key}"
        assert "fa" in bidar.I18N[key], f"Missing 'fa' for {key}"
    print(f"  ✓ PASS — all {len(required_keys)} keys present (en+fa)")

    # ─── Test 6: Progress callback fires every 500 ───
    print("\nTEST 6: Progress callback frequency (every 500 chats)")
    big_dialogs = [
        _make_dialog(f"Chat {i}", i, is_user=True, messages=[
            _make_message(i, "ali here")
        ])
        for i in range(1, 1201)
    ]
    async def big_iter_dialogs():
        for d in big_dialogs:
            yield d
    fake_client.iter_dialogs = big_iter_dialogs

    progress_calls = []
    async def track_progress(done, total, matches):
        progress_calls.append((done, total, matches))

    await bidar._search_all_chats(
        "ali", only_restricted=False, on_progress=track_progress
    )
    # Should fire at idx=499 (500th), 999 (1000th); NOT at 1200 (not %500==0)
    expected_dones = [500, 1000]
    actual_dones = [c[0] for c in progress_calls]
    assert actual_dones == expected_dones, \
        f"Expected progress at {expected_dones}, got {actual_dones}"
    print(f"  ✓ PASS — progress fired at {actual_dones}")

    print("\n" + "=" * 50)
    print("✅ ALL TESTS PASSED")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(_run_tests())
