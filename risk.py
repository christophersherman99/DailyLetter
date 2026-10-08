"""Portfolio risk analytics: beta, volatility, value at risk, drawdowns, Sharpe ratio,
correlations, and a look-through of fund holdings to show true exposure."""
import math
from collections import defaultdict

import pandas as pd
import yfinance as yf

TRADING_DAYS = 252
VAR_LEVEL = 5  # percentile: a 1-in-20 bad day
INTL_WORDS = ("Foreign", "World", "Emerging", "International", "Global", "Europe",
              "Pacific", "China", "Japan")
SECTOR_NAMES = {
    "technology": "Technology", "financialservices": "Financials",
    "healthcare": "Health care", "consumercyclical": "Cons. discretionary",
    "communicationservices": "Communication", "industrials": "Industrials",
    "consumerdefensive": "Cons. staples", "energy": "Energy", "utilities": "Utilities",
    "realestate": "Real estate", "basicmaterials": "Materials",
}
BENCHMARK_FUND = "VOO"  # its sector mix stands in for the S&P 500's


def _sector(raw):
    key = str(raw).lower().replace(" ", "").replace("_", "")
    return SECTOR_NAMES.get(key, "Other")


def risk_view(history, spx, rf_rate):
    """Risk stats for a daily portfolio value series vs the S&P 500 over the same days.

    history: daily portfolio value (today's holdings, as if held the whole period)
    spx: S&P 500 daily closes
    rf_rate: annual risk-free rate as a decimal, for the Sharpe ratio
    """
    spx = spx.reindex(history.index).ffill()
    rp, rm = history.pct_change().dropna(), spx.pct_change().dropna()
    rp, rm = rp.align(rm, join="inner")
    years = len(rp) / TRADING_DAYS

    def annual(r, s):
        ret = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
        vol = r.std() * math.sqrt(TRADING_DAYS)
        return ret, vol, (ret - rf_rate) / vol if vol else 0.0

    p_ret, p_vol, p_sharpe = annual(rp, history)
    m_ret, m_vol, m_sharpe = annual(rm, spx)
    drawdown = history / history.cummax() - 1
    return {
        "beta": rp.cov(rm) / rm.var(),
        "vol": p_vol * 100, "spx_vol": m_vol * 100,
        "ret_1y": (history.iloc[-1] / history.iloc[0] - 1) * 100,
        "spx_ret_1y": (spx.iloc[-1] / spx.iloc[0] - 1) * 100,
        "sharpe": p_sharpe, "spx_sharpe": m_sharpe,
        "var_pct": -rp.quantile(VAR_LEVEL / 100) * 100,
        "var_usd": -rp.quantile(VAR_LEVEL / 100) * history.iloc[-1],
        "max_dd": drawdown.min() * 100, "off_peak": drawdown.iloc[-1] * 100,
        "days": len(rp),
    }


def correlations(prices):
    """Most and least correlated pairs among holdings, from daily returns."""
    rets = pd.DataFrame(prices).ffill().pct_change().dropna()
    corr = rets.corr()
    pairs = [(corr.iloc[i, j], a, b) for i, a in enumerate(corr.columns)
             for j, b in enumerate(corr.columns) if i < j]
    if not pairs:
        return None
    pairs.sort()
    return {"most": pairs[-1], "least": pairs[0],
            "average": sum(c for c, _, _ in pairs) / len(pairs)}


def exposure_view(rows):
    """Look inside funds to find true sector, region, and single-company exposure.

    rows: holdings with ticker, value, and cash flag. Funds count only their top 10
    holdings for single-company exposure, so those numbers are a floor.
    """
    total = sum(r["value"] for r in rows)
    sectors, regions = defaultdict(float), defaultdict(float)
    companies, names, via = defaultdict(float), {}, defaultdict(list)
    benchmark = None
    funds = []

    for r in rows:
        value = r["value"]
        if r["cash"]:
            sectors["Cash"] += value
            regions["Cash"] += value
            continue
        t = yf.Ticker(r["ticker"])
        try:
            info = t.info
        except Exception:
            info = {}
        if info.get("quoteType") == "ETF":
            funds.append(r["ticker"])
            try:
                fd = t.funds_data
                weights = fd.sector_weightings
                category = fd.fund_overview.get("categoryName") or ""
                top = fd.top_holdings
            except Exception:
                sectors["Other"] += value
                regions["US"] += value
                continue
            covered = sum(weights.values()) or 1
            for key, w in weights.items():
                sectors[_sector(key)] += value * w / covered
            if r["ticker"] == BENCHMARK_FUND:
                benchmark = {_sector(k): w / covered * 100 for k, w in weights.items()}
            region = "International" if any(w in category for w in INTL_WORDS) else "US"
            regions[region] += value
            for sym, h in top.iterrows():
                companies[sym] += value * h["Holding Percent"]
                names.setdefault(sym, h["Name"])
                via[sym].append(r["ticker"])
        else:
            sectors[_sector(info.get("sector", ""))] += value
            regions["US" if info.get("country", "United States") == "United States"
                    else "International"] += value
            companies[r["ticker"]] += value
            names[r["ticker"]] = info.get("shortName") or r["ticker"]
            via[r["ticker"]].insert(0, "shares")

    if benchmark is None:
        try:
            fd = yf.Ticker(BENCHMARK_FUND).funds_data
            covered = sum(fd.sector_weightings.values()) or 1
            benchmark = {_sector(k): w / covered * 100
                         for k, w in fd.sector_weightings.items()}
        except Exception:
            benchmark = {}

    pct = lambda d: {k: v / total * 100 for k, v in sorted(d.items(), key=lambda kv: -kv[1])}
    top = sorted(companies.items(), key=lambda kv: -kv[1])[:5]
    return {
        "sectors": pct(sectors), "regions": pct(regions), "benchmark": benchmark,
        "top": [{"ticker": s, "name": names[s], "value": v, "pct": v / total * 100,
                 "via": via[s]} for s, v in top],
        "funds": funds, "companies": dict(companies), "names": names, "total": total,
    }
