from __future__ import annotations

import shutil
import sys

import pytest

from jarvis.interfaces.api import local_music


def test_backend_prefers_macos_when_nowplaying_cli_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    assert local_music._backend() == "macos"


def test_backend_is_linux_when_no_nowplaying_cli_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "platform", "linux")
    assert local_music._backend() == "linux"


def test_backend_none_when_no_tool_and_not_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert local_music._backend() is None


def test_state_from_mpris_playing_track() -> None:
    metadata = {
        "xesam:title": "bad guy",
        "xesam:artist": ["BillieEilishVEVO"],
        "xesam:album": "WHEN WE ALL FALL ASLEEP",
        "mpris:artUrl": "file:///tmp/art.png",
        "mpris:length": 205941000,  # microsecondes
    }
    state = local_music._state_from_mpris("Playing", metadata, 155009342)
    assert state == {
        "connected": True,
        "is_playing": True,
        "track": "bad guy",
        "artist": "BillieEilishVEVO",
        "album": "WHEN WE ALL FALL ASLEEP",
        "album_art": "file:///tmp/art.png",
        "progress_ms": 155009,
        "duration_ms": 205941,
    }


def test_state_from_mpris_joins_multiple_artists() -> None:
    metadata = {"xesam:title": "Song", "xesam:artist": ["A", "B"], "mpris:length": 0}
    state = local_music._state_from_mpris("Paused", metadata, 0)
    assert state["artist"] == "A, B"
    assert state["is_playing"] is False
    assert state["album_art"] is None


def test_state_from_mpris_no_title_means_nothing_playing() -> None:
    state = local_music._state_from_mpris("Stopped", {"xesam:title": ""}, 0)
    assert state == {"connected": True, "is_playing": False, "track": None}
