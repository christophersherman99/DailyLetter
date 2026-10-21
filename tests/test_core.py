"""Offline tests on synthetic data: model math, regime rules, privacy guarantees."""
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DRY_RUN", "1")

import daily_letter  # noqa: E402
import dcf  # noqa: E402
import history  # noqa: E402
import regime  # noqa: E402
import risk  # noqa: E402
import shadow  # noqa: E402

DAYS = pd.bdate_range("2025-01-01", periods=300)


def walk(drift, vol, seed, start=100.0):
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.cumprod(1 + drift + vol * rng.standard_normal(len(DAYS))), DAYS)


# ---------- privacy ----------
def test_scrub_removes_personal_dollars_but_keeps_prices():
    text = "Barclays fell 2.9% (-$17) and Apple added +$5.26, trading at $328.10."
    out = history.scrub(text)
    assert "$17" not in out and "5.26" not in out
    assert "$328.10" in out
    assert history.scrub(["lost -$1,474 today"]) == ["lost today"]


def test_public_data_has_no_dollar_values_or_share_counts():
    forbidden_cols = {"shares", "value", "cost_basis", "day_usd", "gain_usd", "var_usd"}
    data = os.path.join(ROOT, "data")
    for name in os.listdir(data):
        path = os.path.join(data, name)
        text = open(path, encoding="utf-8").read()
        assert not re.search(r"[+-]\s?\$\d", text), f"signed dollar amount in {name}"
        if name.endswith(".csv"):
            assert not forbidden_cols & set(pd.read_csv(path, nrows=0).columns), name


def test_holdings_file_is_never_committed():
    ignored = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read().split()
    assert "portfolio.csv" in ignored


def test_portfolio_reader_handles_byte_order_mark(tmp_path, monkeypatch):
    (tmp_path / "portfolio.csv").write_bytes(
        "﻿ticker,shares,avg_cost\r\n aapl ,3,197.86\r\nSPAXX,23.82,1\r\n".encode("utf-8"))
    monkeypatch.setattr(daily_letter, "HERE", str(tmp_path))
    rows = daily_letter.load_portfolio()
    assert rows[0] == {"ticker": "AAPL", "shares": 3.0, "avg_cost": 197.86}
    assert len(rows) == 2


# ---------- DCF ----------
def model_inputs(**kw):
    inp = {"revenue": 100.0, "fcf_margin": 0.10, "growth": [0.0, 0.0], "debt": 0.0, "cash": 0.0,
           "shares": 1.0, "price": 50.0}
    inp.update(kw)
    return inp


def test_growth_path_fades_to_terminal():
    path = dcf.growth_path(0.20, 0.10, 0.025)
    assert len(path) == dcf.YEARS
    assert path[:2] == [0.20, 0.10]
    assert path[-1] == pytest.approx(0.025)
    assert all(a >= b for a, b in zip(path[1:], path[2:]))


def test_dcf_matches_hand_calculation_for_flat_company():
    # Flat revenue, 10% margin: FCF of 10 a year; terminal value at 10% discount, 0% growth = 100
    v = dcf.value(model_inputs(), 0.10, 0.0, growth=[0.0] * dcf.YEARS)
    annuity = sum(10 / 1.1 ** t for t in range(1, dcf.YEARS + 1))
    terminal = 100 / 1.1 ** dcf.YEARS
    assert v["per_share"] == pytest.approx(annuity + terminal)
    assert v["per_share"] == pytest.approx(100.0)  # a flat perpetuity is worth FCF / rate


def test_dcf_subtracts_debt_and_adds_cash():
    base = dcf.value(model_inputs(), 0.10, 0.0, growth=[0.0] * dcf.YEARS)["per_share"]
    levered = dcf.value(model_inputs(debt=30.0, cash=5.0), 0.10, 0.0,
                        growth=[0.0] * dcf.YEARS)["per_share"]
    assert levered == pytest.approx(base - 25.0)


def test_reverse_dcf_recovers_the_growth_used_to_set_the_price():
    inp = model_inputs()
    inp["price"] = dcf.value(inp, 0.09, 0.025, growth=[0.07] * dcf.YEARS)["per_share"]
    assert dcf.implied_growth(inp, 0.09, 0.025) == pytest.approx(0.07, abs=1e-4)


def test_dcf_rejects_discount_rate_below_growth():
    assert dcf.value(model_inputs(), 0.02, 0.025) is None


# ---------- risk ----------
def test_market_has_beta_one_and_matching_volatility():
    spx = walk(0.0004, 0.01, seed=1)
    r = risk.risk_view(spx, spx, rf_rate=0.04)
    assert r["beta"] == pytest.approx(1.0)
    assert r["vol"] == pytest.approx(r["spx_vol"])
    assert r["var_pct"] > 0 and r["max_dd"] <= 0


def test_leveraged_portfolio_has_double_beta():
    spx = walk(0.0004, 0.01, seed=2)
    double = (1 + 2 * spx.pct_change().fillna(0)).cumprod() * 100
    assert risk.risk_view(double, spx, 0.04)["beta"] == pytest.approx(2.0, rel=1e-6)


# ---------- regime ----------
def regime_data(spx_drift, vix_level):
    spx = walk(spx_drift, 0.004, seed=3)
    flat = pd.Series(100.0, DAYS)
    return {"^GSPC": spx, "RSP": spx, "SMH": spx, "^VIX": pd.Series(vix_level, DAYS),
            "^VIX3M": pd.Series(vix_level + 2.0, DAYS), "HYG": flat, "IEF": flat,
            "GLD": flat, "^TNX": pd.Series(4.5, DAYS), "^IRX": pd.Series(4.0, DAYS),
            "DX-Y.NYB": flat}


def test_steady_rally_reads_calm():
    r = regime.regime(regime_data(0.002, 13.0))
    assert r["name"] == "Calm" and r["flags"] == 0


def test_selloff_with_high_fear_reads_stressed():
    r = regime.regime(regime_data(-0.003, 32.0))
    levels = {s["name"]: s["level"] for s in r["signals"]}
    assert levels["Trend"] == regime.STRESS and levels["Fear gauge"] == regime.STRESS
    assert r["name"] in ("Mixed", "Stressed")


# ---------- shadow portfolios ----------
def test_shadow_weights_are_normalized(tmp_path, monkeypatch):
    path = tmp_path / "shadows.csv"
    path.write_text("portfolio,ticker,weight,since\nTest,VOO,35,2026-10-07\nTest,GLD,70,2026-10-07\n")
    monkeypatch.setattr(shadow, "PATH", str(path))
    w = shadow.load()["Test"]["weights"]
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["GLD"] == pytest.approx(2 / 3)
