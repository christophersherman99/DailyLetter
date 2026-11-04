"""Weekly attribution: contributions must add up to the portfolio's weekly return."""
import os
import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weekly  # noqa: E402

DAYS = pd.bdate_range("2026-10-09", "2026-10-16")  # Fri, then Mon-Fri
DATA = {"AAA": pd.Series([100, 101, 103, 102, 104, 110.0], DAYS),
        "BBB": pd.Series([50, 49, 48, 47, 46, 45.0], DAYS)}
HOLDINGS = [{"ticker": "AAA", "shares": 3, "avg_cost": 90},
            {"ticker": "BBB", "shares": 4, "avg_cost": 60},
            {"ticker": "SPAXX", "shares": 100, "avg_cost": 1}]


def test_week_runs_from_prior_friday_to_this_friday():
    ref, end = weekly.week_bounds(DATA["AAA"], date(2026, 10, 17))  # a Saturday
    assert ref == pd.Timestamp("2026-10-09") and end == pd.Timestamp("2026-10-16")


def test_blank_cells_in_saved_data_come_back_as_none(tmp_path, monkeypatch):
    (tmp_path / "catalysts.csv").write_text(
        "date,ticker,source,type,day_pct,headline,link\n"
        "2026-10-14,BCS,holding,Legal,,Probe widens,\n"
        "2026-10-15,MCD,holding,Capital,1.2,Buyback,https://example.com/a\n")
    monkeypatch.setattr(weekly.history, "DATA", str(tmp_path))
    rows = weekly._rows_in_week("catalysts", pd.Timestamp("2026-10-09"), pd.Timestamp("2026-10-16"))
    assert rows[0]["link"] is None and rows[0]["day_pct"] is None
    assert rows[1]["link"] == "https://example.com/a"


def test_weekly_page_renders_with_missing_links_and_numbers():
    w = {"ref": date(2026, 10, 9), "end": date(2026, 10, 16), "you": 0.5, "spx": 1.0,
         "shadows": {"Conservative": 0.3}, "world": {"US": {"S&P 500": 1.0, "Nasdaq": None}},
         "sectors": {}, "macro": {}, "tnx_bps": None, "regimes": [("2026-10-16", "Calm")],
         "rows": [{"ticker": "AAA", "ret": 2.0, "weight": 60.0, "contrib": 1.2, "cash": False}],
         "catalysts": [{"ticker": "BCS", "type": None, "headline": "Probe widens", "link": None}],
         "results": [{"ticker": "AAA", "eps": 1.1, "eps_est": 1.0, "surprise_pct": None,
                      "reaction_pct": None}],
         "letters": [], "ahead": [], "events": []}
    page = weekly.html(w, None)
    assert "Probe widens" in page and "The Weekly Wrap" in page


def test_contributions_sum_to_the_portfolio_return():
    ref, end = weekly.week_bounds(DATA["AAA"], date(2026, 10, 17))
    rows, total = weekly.attribution(HOLDINGS, DATA, ref, end)
    start = 3 * 100 + 4 * 50 + 100
    finish = 3 * 110 + 4 * 45 + 100
    assert total == pytest.approx((finish / start - 1) * 100)
    assert sum(r["weight"] for r in rows) == pytest.approx(100)
    assert rows[0]["ticker"] == "AAA"  # sorted by contribution, biggest first
