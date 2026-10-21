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


def test_contributions_sum_to_the_portfolio_return():
    ref, end = weekly.week_bounds(DATA["AAA"], date(2026, 10, 17))
    rows, total = weekly.attribution(HOLDINGS, DATA, ref, end)
    start = 3 * 100 + 4 * 50 + 100
    finish = 3 * 110 + 4 * 45 + 100
    assert total == pytest.approx((finish / start - 1) * 100)
    assert sum(r["weight"] for r in rows) == pytest.approx(100)
    assert rows[0]["ticker"] == "AAA"  # sorted by contribution, biggest first
