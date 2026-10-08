"""Stress tests: what today's holdings would have lost in real past selloffs, what they
would lose in hypothetical shocks, and how much of the portfolio rides on the AI trade.

Historical replays apply each holding's actual return over a past window to its value
today. Hypothetical shocks use each holding's beta to a factor (the S&P 500, or chip
stocks as the AI-trade proxy) estimated from the past year of daily returns.
"""
import pandas as pd
import yfinance as yf

HISTORY_START = "2019-12-01"
REPLAYS = {
    "COVID crash (Feb-Mar 2020)": ("2020-02-19", "2020-03-23"),
    "2022 bear market": ("2022-01-03", "2022-10-12"),
    "Yen carry unwind (Jul-Aug 2024)": ("2024-07-10", "2024-08-05"),
    "Tariff shock (Feb-Apr 2025)": ("2025-02-19", "2025-04-08"),
}
# Older funds that stand in for a holding during windows before it existed
PROXIES = {"SGOV": "BIL"}
SHOCKS = {  # name: (factor ticker, move)
    "Chip stocks fall 30%": ("SMH", -0.30),
    "S&P 500 falls 20%": ("^GSPC", -0.20),
}
# Companies at the center of the AI trade, by Yahoo symbol (fund holdings use local listings)
AI_NAMES = {"NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "AMD", "ORCL", "TSM",
            "2330.TW", "ASML", "ASML.AS", "MU", "005930.KS", "005930.KQ", "000660.KS",
            "000660.KQ", "PLTR", "ARM", "TSLA", "AAPL"}


def _price_on(s, day):
    """Close on `day`, or the last close before it."""
    s = s[s.index <= pd.Timestamp(day)]
    return float(s.iloc[-1]) if len(s) else None


def replays(rows, spx_ticker="^GSPC"):
    """Replay past selloffs on today's holdings. Holdings without history for a window
    (not yet listed) use a similar older fund from PROXIES, else the S&P 500's move, and
    are reported as proxied."""
    held = [r["ticker"] for r in rows if not r["cash"]]
    tickers = sorted(set(held + [PROXIES[t] for t in held if t in PROXIES] + [spx_ticker]))
    df = yf.download(tickers, start=HISTORY_START, auto_adjust=True, group_by="ticker",
                     progress=False, threads=True)
    closes = {t: df[t]["Close"].dropna() for t in tickers if t in df.columns.levels[0]}
    total = sum(r["value"] for r in rows)
    out = []
    for name, (start, end) in REPLAYS.items():
        spx = closes[spx_ticker]
        spx_ret = _price_on(spx, end) / _price_on(spx, start) - 1
        loss, proxied = 0.0, []
        for r in rows:
            if r["cash"]:
                continue
            ret = None
            for candidate in (r["ticker"], PROXIES.get(r["ticker"])):
                s = closes.get(candidate)
                if s is not None and len(s) and s.index[0] <= pd.Timestamp(start):
                    ret = _price_on(s, end) / _price_on(s, start) - 1
                    break
            if candidate != r["ticker"] or ret is None:
                proxied.append(r["ticker"])
            if ret is None:
                ret = spx_ret
            loss += r["value"] * ret
        out.append({"name": name, "usd": loss, "pct": loss / total * 100,
                    "spx_pct": spx_ret * 100, "proxied": proxied})
    return out


def shocks(rows, data):
    """Hypothetical factor shocks via each holding's 1-year beta to the factor."""
    total = sum(r["value"] for r in rows)
    out = []
    for name, (factor, move) in SHOCKS.items():
        f = data.get(factor)
        if f is None:
            continue
        fr = f.pct_change().dropna().iloc[-252:]
        loss, betas = 0.0, {}
        for r in rows:
            if r["cash"] or r["ticker"] not in data:
                continue
            hr, aligned = data[r["ticker"]].pct_change().dropna().align(fr, join="inner")
            beta = hr.cov(aligned) / aligned.var() if len(hr) > 60 else 1.0
            betas[r["ticker"]] = beta
            loss += r["value"] * beta * move
        out.append({"name": name, "usd": loss, "pct": loss / total * 100, "betas": betas})
    return out


def ai_exposure(exposure):
    """Share of the portfolio in AI-trade companies, counting fund look-through.
    Funds only report their top 10 holdings, so this is a floor."""
    if not exposure:
        return None
    companies = exposure["companies"]
    ai = {s: v for s, v in companies.items() if s in AI_NAMES}
    total = exposure["total"]
    return {"pct": sum(ai.values()) / total * 100, "usd": sum(ai.values()),
            "names": sorted(ai.items(), key=lambda kv: -kv[1])}
