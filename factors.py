"""Factor exposure: a multiple regression of daily returns on long-short factor returns built
from ETFs, the same idea as academic factor models (Fama-French) using tradable proxies.

Each factor is the daily return of one fund minus another, so a loading of +0.3 on Value means
the portfolio has tended to gain 0.3% for every 1% that value stocks beat growth stocks,
holding the other factors fixed.
"""
import numpy as np
import pandas as pd

FACTORS = {  # name: (long, short) or (long, None) for the market itself
    "Market": ("^GSPC", None),
    "Size": ("IWM", "^GSPC"),
    "Value": ("IWD", "IWF"),
    "Momentum": ("MTUM", "^GSPC"),
    "International": ("EFA", "^GSPC"),
}
EXPLAIN = {
    "Market": ("moves more than the market", "moves less than the market"),
    "Size": ("leans toward small companies", "leans toward large companies"),
    "Value": ("leans toward value stocks", "leans toward growth stocks"),
    "Momentum": ("leans into recent winners", "leans away from recent winners"),
    "International": ("behaves partly like foreign stocks", "behaves like US stocks"),
}
TICKERS = sorted({t for pair in FACTORS.values() for t in pair if t})


def factor_returns(data, days=252):
    rets = {t: data[t].pct_change() for t in TICKERS if t in data}
    out = {}
    for name, (long, short) in FACTORS.items():
        if long in rets and (short is None or short in rets):
            out[name] = rets[long] - (rets[short] if short else 0)
    return pd.DataFrame(out).dropna().iloc[-days:]


def regress(returns, factors):
    """OLS loadings, t-statistics, and R-squared of `returns` on the factor columns."""
    y, X = returns.align(factors, join="inner", axis=0)
    X = X.dropna()
    y = y.reindex(X.index).dropna()
    X = X.reindex(y.index)
    A = np.column_stack([np.ones(len(X)), X.values])
    coef, *_ = np.linalg.lstsq(A, y.values, rcond=None)
    resid = y.values - A @ coef
    dof = max(len(y) - A.shape[1], 1)
    sigma2 = resid @ resid / dof
    se = np.sqrt(np.diag(sigma2 * np.linalg.pinv(A.T @ A)))
    r2 = 1 - (resid @ resid) / ((y.values - y.values.mean()) @ (y.values - y.values.mean()))
    return {"loadings": dict(zip(X.columns, coef[1:])),
            "t": dict(zip(X.columns, coef[1:] / se[1:])),
            "alpha_annual": coef[0] * 252 * 100, "r2": r2, "days": len(y)}


def describe(loadings, t):
    """Plain-English reading of the statistically meaningful tilts (|t| >= 2)."""
    parts = []
    for name, beta in loadings.items():
        if name == "Market":
            if abs(beta - 1) >= 0.1:
                parts.append(EXPLAIN[name][0 if beta > 1 else 1])
        elif abs(t.get(name, 0)) >= 2 and abs(beta) >= 0.05:
            parts.append(EXPLAIN[name][0 if beta > 0 else 1])
    return parts


def analyze(portfolio_history, holdings_prices, data):
    f = factor_returns(data)
    port = regress(portfolio_history.pct_change().dropna(), f)
    per_holding = {}
    for t, s in holdings_prices.items():
        try:
            per_holding[t] = regress(s.pct_change().dropna(), f)["loadings"]
        except Exception:
            continue
    rets = pd.DataFrame({t: s.pct_change() for t, s in holdings_prices.items()}).dropna().iloc[-252:]
    corr = rets.corr()
    return {"portfolio": port, "reading": describe(port["loadings"], port["t"]),
            "holdings": per_holding, "factors": list(FACTORS),
            "correlation": {"tickers": list(corr.columns), "matrix": corr.round(3).values.tolist()}}
