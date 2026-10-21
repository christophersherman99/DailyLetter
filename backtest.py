"""Does the weather work? Replays the Market Weather rules (regime.py) weekly over history
and measures what the S&P 500 did next under each reading.

For each week, the regime is computed from data available that day only (no look-ahead).
The rules and thresholds were set before this test was run, not fitted to it, but this is
still an in-sample historical study, not a forecast.
"""
import pandas as pd
import yfinance as yf

import regime

START = "2010-01-01"
FIRST_SIGNAL = "2011-01-01"   # leave a year for 200-day averages to warm up
HORIZONS = {"1 month": 21, "3 months": 63}


def history(start=START):
    tickers = list(regime.TICKERS.values())
    df = yf.download(tickers, start=start, auto_adjust=True, group_by="ticker",
                     progress=False, threads=True)
    return {t: df[t]["Close"].dropna() for t in tickers if t in df.columns.levels[0]}


def weekly_regimes(data):
    """[(date, regime name, score)] for each Friday (or last trading day of the week)."""
    spx = data["^GSPC"]
    weeks = spx[spx.index >= FIRST_SIGNAL].resample("W-FRI").last().dropna().index
    out = []
    for week in weeks:
        day = spx.index[spx.index <= week][-1]
        sliced = {t: s[s.index <= day] for t, s in data.items()}
        r = regime.regime(sliced)
        out.append((day, r["name"], r["score"]))
    return out


def run(data=None):
    data = data or history()
    spx = data["^GSPC"]
    rows = []
    for day, name, score in weekly_regimes(data):
        i = spx.index.get_loc(day)
        row = {"date": day, "regime": name, "score": score}
        for label, n in HORIZONS.items():
            if i + n < len(spx):
                window = spx.iloc[i:i + n + 1]
                row[label] = (float(window.iloc[-1]) / float(window.iloc[0]) - 1) * 100
                row[label + " drawdown"] = (float((window / window.cummax()).min()) - 1) * 100
        rows.append(row)
    df = pd.DataFrame(rows)

    def summarize(frame):
        out = {"weeks": len(frame), "share": len(frame) / len(df) * 100}
        for label in HORIZONS:
            r = frame[label].dropna()
            dd = frame[label + " drawdown"].dropna()
            out[label] = {"avg": r.mean(), "median": r.median(), "pct_negative": (r < 0).mean() * 100,
                          "avg_drawdown": dd.mean(), "worst": r.min()} if len(r) else None
        return out

    summary = {name: summarize(df[df["regime"] == name])
               for name in ("Calm", "Mixed", "Stressed") if (df["regime"] == name).any()}
    summary["All weeks"] = summarize(df)
    return {"since": str(df["date"].iloc[0].date()), "weeks": len(df), "summary": summary,
            "timeline": {"dates": [d.strftime("%Y-%m-%d") for d in df["date"]],
                         "score": df["score"].tolist(),
                         "spx": [float(spx.loc[d]) for d in df["date"]]}}


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result["summary"], indent=1, default=lambda x: round(float(x), 2)))
