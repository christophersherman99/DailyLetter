"""Build site/data.json for the public dashboard (GitHub Pages).

Everything written here is percentages, weights, index levels, or market data, never the
portfolio's dollar size. The browser does the interactive math: the rebalancing simulator
gets each ticker's daily returns, crash-window returns, and AI share, and the DCF playground
gets each company's model inputs.
"""
import json
import os
import time
from datetime import datetime

import pandas as pd
import yfinance as yf

import daily_letter as dl
import dcf
import history
import regime
import risk
import shadow
import stress

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
# Building blocks offered in the simulator besides current holdings and shadow mixes
EXTRAS = {"QQQ": "Nasdaq 100", "SCHD": "Dividend stocks", "BND": "US bonds",
          "GLD": "Gold", "SGOV": "T-bills", "XLP": "Consumer staples", "B": "Barrick (gold miner)"}


def _r(x, n=4):
    return None if x is None or x != x else round(float(x), n)


def _series(s):
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [_r(v) for v in s]}


def ai_share(ticker, info):
    """Fraction of a ticker that sits in AI-trade companies (funds: top 10 holdings only)."""
    if info.get("quoteType") != "ETF":
        return 1.0 if ticker in stress.AI_NAMES else 0.0
    try:
        top = yf.Ticker(ticker).funds_data.top_holdings
        return float(sum(h["Holding Percent"] for s, h in top.iterrows() if s in stress.AI_NAMES))
    except Exception:
        return 0.0


def replay_returns(tickers):
    """{ticker: {scenario: return}} over each historical window, using PROXIES if needed."""
    want = sorted(set(tickers) | {stress.PROXIES[t] for t in tickers if t in stress.PROXIES}
                  | {"^GSPC"})
    df = yf.download(want, start=stress.HISTORY_START, auto_adjust=True, group_by="ticker",
                     progress=False, threads=True)
    closes = {t: df[t]["Close"].dropna() for t in want if t in df.columns.levels[0]}
    out = {}
    for t in list(tickers) + ["^GSPC"]:
        out[t] = {}
        for name, (start, end) in stress.REPLAYS.items():
            for c in (t, stress.PROXIES.get(t)):
                s = closes.get(c)
                if s is not None and len(s) and s.index[0] <= pd.Timestamp(start):
                    out[t][name] = _r(stress._price_on(s, end) / stress._price_on(s, start) - 1, 5)
                    break
            else:
                out[t][name] = None
    return out


def main():
    holdings = dl.load_portfolio()
    shadows = shadow.load()
    held = [h["ticker"] for h in holdings if h["ticker"] not in dl.CASH]
    universe = sorted(set(held) | set(shadow.tickers()) | set(EXTRAS))
    data = dl.download(universe + ["^GSPC", dl.RISK_FREE] + list(regime.TICKERS.values()))
    port = dl.portfolio_view(holdings, data)
    spx = data["^GSPC"]

    # Daily returns on a common calendar (the past year of US trading days)
    days = spx.index[-253:]
    closes = pd.DataFrame({t: data[t] for t in universe if t in data}).reindex(days).ffill()
    rets = closes.pct_change().iloc[1:]
    spx_rets = spx.reindex(days).pct_change().iloc[1:]

    infos = {}
    for t in universe:
        try:
            infos[t] = yf.Ticker(t).info
        except Exception:
            infos[t] = {}
    replays = replay_returns([t for t in universe if t in rets])
    blocks = [{
        "ticker": t, "name": EXTRAS.get(t) or infos[t].get("shortName") or t,
        "kind": "fund" if infos[t].get("quoteType") == "ETF" else "stock",
        "returns": [_r(v, 6) for v in rets[t].fillna(0)], "replays": replays.get(t, {}),
        "ai": _r(ai_share(t, infos[t]), 4),
    } for t in universe if t in rets]

    current = {r["ticker"]: _r(r["weight"] / 100, 5) for r in port["rows"] if not r["cash"]}
    cash = sum(r["weight"] for r in port["rows"] if r["cash"]) / 100
    if cash:  # cash sits in T-bills in the simulator, the closest building block
        current["SGOV"] = _r(current.get("SGOV", 0) + cash, 5)
    presets = {"Current": current}
    presets.update({name: {t: _r(w, 5) for t, w in p["weights"].items()}
                    for name, p in shadows.items()})

    # Performance over the past year, every line indexed to 100
    perf = {"You": port["history_1y"], "S&P 500": spx}
    for name, p in shadows.items():
        frame = pd.DataFrame({t: data[t] / float(data[t].iloc[-1]) * w
                              for t, w in p["weights"].items() if t in data})
        perf[name] = frame.ffill().dropna().sum(axis=1)
    performance = {}
    for name, s in perf.items():
        s = s.reindex(days).ffill().dropna()
        performance[name] = _series(s / float(s.iloc[0]) * 100)

    rf = float(data[dl.RISK_FREE].iloc[-1]) / 100
    risk_now = risk.risk_view(port["history_1y"], spx, rf)
    exposure = risk.exposure_view(port["rows"])
    weather = regime.regime(data)
    for s in weather["signals"]:
        s["reading"] = s["reading"].replace("&amp;", "&")
        s["why"] = s["why"].replace("&amp;", "&")

    dcf_inputs = []
    rf10 = dl.stats(data["^TNX"], "^TNX")["last"] / 100 if "^TNX" in data else rf
    for t in held:
        inp = None
        for attempt in range(3):  # Yahoo throttles bursts of fundamentals requests; retry
            try:
                inp, reason = dcf.gather(t, rf10)
                break
            except Exception as e:
                print(f"DCF inputs for {t} failed (attempt {attempt + 1}):", e)
                time.sleep(5 * (attempt + 1))
        if inp:
            inp.update(dcf.wacc(inp))
            dcf_inputs.append({k: (_r(v, 6) if isinstance(v, float) else v)
                               for k, v in inp.items()})

    def csv(name):
        path = os.path.join(history.DATA, f"{name}.csv")
        if not os.path.exists(path):
            return []
        return json.loads(pd.read_csv(path, dtype={"date": str}).to_json(orient="records"))

    site = {
        "generated": datetime.now(dl.ET).strftime("%Y-%m-%d %H:%M %Z"),
        "rf": _r(rf, 5), "years": dcf.YEARS, "erp": dcf.EQUITY_RISK_PREMIUM,
        "terminal_growth": dcf.TERMINAL_GROWTH,
        "weather": weather,
        "risk": {k: _r(v) for k, v in risk_now.items() if k != "var_usd"},  # no dollars
        "gain_pct": _r(port["gain"]),
        "weights": [{"ticker": r["ticker"], "weight": _r(r["weight"], 3), "cash": r["cash"],
                     "day_pct": _r(r["day"]), "gain_pct": _r(r["since_bought"])}
                    for r in port["rows"]],
        "exposure": {"sectors": {k: _r(v, 2) for k, v in exposure["sectors"].items()},
                     "benchmark": {k: _r(v, 2) for k, v in exposure["benchmark"].items()},
                     "regions": {k: _r(v, 2) for k, v in exposure["regions"].items()},
                     "top": [{"ticker": c["ticker"], "name": c["name"], "pct": _r(c["pct"], 2),
                              "via": c["via"]} for c in exposure["top"]]},
        "ai_exposure": _r((stress.ai_exposure(exposure) or {}).get("pct"), 2),
        "spx_returns": [_r(v, 6) for v in spx_rets.fillna(0)],
        "spx_replays": replays.get("^GSPC", {}),
        "scenarios": list(stress.REPLAYS),
        "blocks": blocks, "presets": presets,
        "performance": performance,
        "dcf": dcf_inputs,
        "daily": csv("portfolio"), "shadows": csv("shadows"), "valuations": csv("valuations"),
        "letters": list(reversed(history.load_letters())),
    }
    os.makedirs(SITE, exist_ok=True)
    with open(os.path.join(SITE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(site, f, separators=(",", ":"), allow_nan=False)
    print("Wrote site/data.json:", len(blocks), "building blocks,", len(dcf_inputs), "DCF models")


if __name__ == "__main__":
    main()
