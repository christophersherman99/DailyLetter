"""The weather backtest must not peek at the future."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest  # noqa: E402
import regime  # noqa: E402

DAYS = pd.bdate_range("2010-01-01", "2012-06-30")


def synthetic(crash_after=None):
    rng = np.random.default_rng(7)
    spx = pd.Series(100 * np.cumprod(1 + 0.0004 + 0.008 * rng.standard_normal(len(DAYS))), DAYS)
    vix = pd.Series(15.0, DAYS)
    if crash_after:
        late = DAYS > pd.Timestamp(crash_after)
        spx[late] *= 0.6
        vix[late] = 45.0
    flat = pd.Series(100.0, DAYS)
    data = {t: flat for t in regime.TICKERS.values()}
    data.update({"^GSPC": spx, "RSP": spx, "SMH": spx, "^VIX": vix, "^VIX3M": vix + 2,
                 "^TNX": pd.Series(4.5, DAYS), "^IRX": pd.Series(4.0, DAYS)})
    return data


def test_readings_before_a_crash_ignore_the_crash():
    calm = dict((d, (n, s)) for d, n, s in backtest.weekly_regimes(synthetic()))
    crashed = dict((d, (n, s)) for d, n, s in backtest.weekly_regimes(synthetic("2012-01-31")))
    before = [d for d in calm if d <= pd.Timestamp("2012-01-31")]
    after = [d for d in calm if d > pd.Timestamp("2012-02-10")]
    assert before and all(calm[d] == crashed[d] for d in before)
    assert any(calm[d] != crashed[d] for d in after)  # and the crash does register once it happens
