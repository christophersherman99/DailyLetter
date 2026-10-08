"""Shadow portfolios: alternative mixes defined in shadows.csv, tracked next to the real
portfolio with the same risk stats, stress tests, and exposure analysis.

Each shadow is scaled to the real portfolio's current value so dollar figures compare
directly. Two views:
  - Since start: a buy-and-hold paper portfolio opened on its `since` date at the real
    portfolio's value that day, compared with the real holdings over the same days.
  - Risk: today's weights held over the past year, through the same risk, stress test,
    and look-through code used for the real portfolio.
"""
import csv
import os
from collections import defaultdict

import pandas as pd

import risk
import stress

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadows.csv")


def load():
    """{name: {"since": "YYYY-MM-DD", "weights": {ticker: fraction}}}"""
    if not os.path.exists(PATH):
        return {}
    out = defaultdict(lambda: {"since": None, "weights": {}})
    with open(PATH, newline="") as f:
        for r in csv.DictReader(f):
            p = out[r["portfolio"].strip()]
            p["weights"][r["ticker"].strip().upper()] = float(r["weight"])
            p["since"] = r["since"].strip()
    for p in out.values():
        total = sum(p["weights"].values())
        p["weights"] = {t: w / total for t, w in p["weights"].items()}
    return dict(out)


def tickers():
    return sorted({t for p in load().values() for t in p["weights"]})


def _since(series, day):
    """Return since `day` (first close on or after it) to the latest close, in percent."""
    s = series[series.index >= pd.Timestamp(day)]
    return (float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100 if len(s) >= 2 else 0.0


def evaluate(port, data, spx, rf):
    """Compare each shadow with the real portfolio. Returns a list of results."""
    value = port["value"]
    results = []
    for name, p in load().items():
        missing = [t for t in p["weights"] if t not in data]
        if missing:
            print(f"Shadow {name} skipped, no data for", missing)
            continue
        rows = [{"ticker": t, "value": value * w, "cash": False, "weight": w * 100}
                for t, w in p["weights"].items()]
        frame = pd.DataFrame({t: data[t] / float(data[t].iloc[-1]) * value * w
                              for t, w in p["weights"].items()})
        history = frame.ffill().dropna().sum(axis=1)
        out = {"name": name, "since": p["since"], "weights": p["weights"], "history": history,
               "since_pct": _since(history, p["since"]),
               "you_since_pct": _since(port["history_1y"], p["since"])}
        for key, fn in (("risk", lambda: risk.risk_view(history, spx, rf)),
                        ("replays", lambda: stress.replays(rows)),
                        ("exposure", lambda: risk.exposure_view(rows))):
            try:
                out[key] = fn()
            except Exception as e:
                print(f"Shadow {name} {key} skipped:", e)
                out[key] = None
        out["ai"] = stress.ai_exposure(out["exposure"])
        results.append(out)
    return results
