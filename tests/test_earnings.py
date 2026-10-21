"""Earnings reaction timing: the report's hour decides which day's close reflects it."""
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import earnings  # noqa: E402

CLOSES = pd.Series([100.0, 102.0, 95.0, 96.0],
                   pd.to_datetime(["2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03"]))


def test_after_close_report_reacts_next_day():
    day = earnings._reaction_day(datetime(2026, 7, 30, 16, 0), CLOSES)
    assert day == pd.Timestamp("2026-07-31")
    assert round(earnings._move_on(day, CLOSES), 2) == round((95 / 102 - 1) * 100, 2)


def test_pre_market_report_reacts_same_day():
    assert earnings._reaction_day(datetime(2026, 7, 30, 7, 0), CLOSES) == pd.Timestamp("2026-07-30")


def test_friday_after_close_report_reacts_monday():
    assert earnings._reaction_day(datetime(2026, 7, 31, 16, 5), CLOSES) == pd.Timestamp("2026-08-03")
