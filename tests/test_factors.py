"""The factor regression must recover loadings planted in synthetic data."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import factors  # noqa: E402


def test_regression_recovers_planted_loadings():
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2025-01-01", periods=400)
    f = pd.DataFrame(rng.normal(0, 0.01, (len(days), 3)), days, ["Market", "Size", "Value"])
    y = 1.2 * f["Market"] - 0.4 * f["Size"] + 0.3 * f["Value"] + rng.normal(0, 0.0005, len(days))
    r = factors.regress(y, f)
    assert r["loadings"]["Market"] == pytest.approx(1.2, abs=0.02)
    assert r["loadings"]["Size"] == pytest.approx(-0.4, abs=0.02)
    assert r["loadings"]["Value"] == pytest.approx(0.3, abs=0.02)
    assert r["r2"] > 0.99


def test_plain_english_reading_skips_weak_tilts():
    reading = factors.describe({"Market": 1.02, "Size": 0.4, "Value": -0.3, "Momentum": 0.2},
                               {"Market": 30, "Size": 5, "Value": -4, "Momentum": 0.8})
    assert reading == ["leans toward small companies", "leans toward growth stocks"]
