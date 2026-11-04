"""Backup runs must not send a second copy of an edition on the same day."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history  # noqa: E402


def test_sent_markers_are_per_edition_and_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DATA", str(tmp_path))
    monkeypatch.setattr(history, "SENT", str(tmp_path / "sent.json"))
    assert not history.already_sent("daily", "2026-11-04")
    history.mark_sent("daily", "2026-11-04")
    assert history.already_sent("daily", "2026-11-04")
    assert not history.already_sent("daily", "2026-11-05")
    assert not history.already_sent("weekly", "2026-11-04")
    history.mark_sent("weekly", "2026-11-07")
    assert history.already_sent("daily", "2026-11-04")  # one edition doesn't erase the other
