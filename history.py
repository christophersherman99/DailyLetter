"""Daily history: each run saves the day's numbers to CSV files in data/ (and the letter's
text to letters.jsonl), so the letter can remember past days and track real performance.
Re-running on the same market day replaces that day's rows instead of duplicating them.

The repo is public, so nothing saved here reveals the portfolio's dollar size: the portfolio
is an index (100 on the first saved day, compounded by daily returns), holdings are weights,
and personal dollar amounts are scrubbed from the AI's text before saving."""
import json
import os
import re

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LETTERS = os.path.join(DATA, "letters.jsonl")
# "(-$17)", "+$5.26", "-$1,474": signed dollar amounts are the reader's own gains and losses
_SIGNED_DOLLARS = re.compile(r"\s*\(\s*[+-]\s?\$[\d,]+(?:\.\d+)?\s*\)|[+-]\s?\$[\d,]+(?:\.\d+)?")


def scrub(text):
    """Remove personal dollar amounts from AI text (share prices like $328.10 are kept)."""
    if not text:
        return text
    if isinstance(text, list):
        return [scrub(t) for t in text]
    return re.sub(r"\s{2,}", " ", _SIGNED_DOLLARS.sub("", text)).replace(" ,", ",").strip()


def _next_index(day, day_pct):
    """Portfolio index for `day`: the prior saved day's index compounded by today's return."""
    path = os.path.join(DATA, "portfolio.csv")
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"date": str})
        old = old[old["date"] < day]
        if len(old) and "index" in old:
            return float(old["index"].iloc[-1]) * (1 + day_pct / 100)
    return 100.0


def _upsert(name, rows, day):
    """Replace the rows for `day` in data/<name>.csv with `rows`."""
    path = os.path.join(DATA, f"{name}.csv")
    new = pd.DataFrame(rows)
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"date": str})
        new = pd.concat([old[old["date"] != day], new], ignore_index=True)
    new.sort_values("date", kind="stable").to_csv(path, index=False, float_format="%.6g")


def save_day(day, port, markets, ai, movers, risk, extra=None):
    """Save one market day. `day` is the US session date as YYYY-MM-DD. `extra` adds
    columns to the portfolio row (market regime, AI exposure)."""
    os.makedirs(DATA, exist_ok=True)
    _upsert("portfolio", [{
        "date": day, "index": round(_next_index(day, port["day"]), 4),
        "day_pct": round(port["day"], 4), "gain_pct": round(port["gain"], 4),
        **({k: round(risk[k], 4) for k in ("beta", "vol", "sharpe", "var_pct", "off_peak")}
           if risk else {}),
        **(extra or {}),
    }], day)
    _upsert("holdings", [{
        "date": day, "ticker": r["ticker"], "price": round(r["price"], 4),
        "day_pct": round(r["day"], 4), "weight": round(r["weight"], 3),
        "gain_pct": round(r["since_bought"], 4),
    } for r in port["rows"]], day)
    _upsert("markets", [{
        "date": day, "group": group, "name": name, "level": round(q["last"], 4),
        "day_pct": round(q["bps"] if "bps" in q else q["day"], 4),
        "unit": "bps" if "bps" in q else "%", "session": str(q["date"]),
    } for group, items in markets.items() for name, q in items.items()], day)

    entry = {"date": day, "take": ai and scrub(ai["take"]),
             "portfolio": ai and scrub(ai["portfolio"]), "watch": ai and scrub(ai["watch"]),
             "deep_dive": ai and scrub(ai.get("deep_dive")),
             "movers": [{"ticker": m["ticker"], "day_pct": round(m["day"], 2)}
                        for m in movers["up"] + movers["down"]]}
    existing = next((e for e in load_letters() if e["date"] == day), None)
    if not ai and existing and existing.get("take"):
        # A run without AI text (e.g. a local test) never erases a saved letter
        entry.update({k: existing.get(k) for k in ("take", "portfolio", "watch", "deep_dive")})
    entries = [e for e in load_letters() if e["date"] != day] + [entry]
    with open(LETTERS, "w", encoding="utf-8") as f:
        for e in sorted(entries, key=lambda e: e["date"]):
            f.write(json.dumps(e) + "\n")


def save_valuation(day, v):
    """Record a deep-dive DCF so each stock builds a history of model values."""
    os.makedirs(DATA, exist_ok=True)
    _upsert("valuations", [{
        "date": day, "ticker": v["ticker"], "price": round(v["price"], 2),
        "model_value": round(v["per_share"], 2), "upside_pct": round(v["upside"] * 100, 2),
        "implied_growth_pct": (round(v["implied_growth"] * 100, 2)
                               if v["implied_growth"] is not None else None),
        "growth_y1_pct": round(v["growth"][0] * 100, 2),
        "growth_y2_pct": round(v["growth"][1] * 100, 2),
        "fcf_margin_pct": round(v["fcf_margin"] * 100, 2), "wacc_pct": round(v["wacc"] * 100, 3),
        "terminal_growth_pct": v["terminal_growth"] * 100, "beta": round(v["beta"], 3),
        "terminal_share_pct": round(v["terminal_share"] * 100, 1),
    }], day)


def save_shadows(day, shadows):
    """Record each shadow portfolio's daily standing next to the real one."""
    if not shadows:
        return
    os.makedirs(DATA, exist_ok=True)
    rows = []
    for sh in shadows:
        r = sh.get("risk") or {}
        rows.append({
            "date": day, "portfolio": sh["name"], "since": sh["since"],
            "since_pct": round(sh["since_pct"], 4), "you_since_pct": round(sh["you_since_pct"], 4),
            **{k: round(r[k], 4) for k in ("beta", "vol", "sharpe", "ret_1y", "max_dd") if k in r},
            "ai_exposure_pct": round(sh["ai"]["pct"], 2) if sh.get("ai") else None,
        })
    _upsert("shadows", rows, day)


def save_catalysts(day, radar):
    """Log each day's tagged catalysts so the dashboard can show a searchable history."""
    rows = [{"date": day, "ticker": i["ticker"], "source": i["source"], "type": i["type"] or "",
             "day_pct": round(i["day"], 2) if i["day"] is not None else None,
             "headline": i["title"], "link": i["link"]}
            for i in radar["items"] if i["title"] and i["type"]]
    rows += [{"date": day, "ticker": w["ticker"], "source": "watchlist", "type": w["type"] or "",
              "day_pct": round(w["day"], 2) if w["day"] is not None else None,
              "headline": w["title"], "link": w["link"]}
             for w in radar["watchlist"] if w["title"]]
    rows += [{"date": day, "ticker": "", "source": "market", "type": m["type"], "day_pct": None,
              "headline": m["title"], "link": m["link"]} for m in radar["market"]]
    if rows:
        os.makedirs(DATA, exist_ok=True)
        _upsert("catalysts", rows, day)


def save_earnings(day, er):
    """Keep every earnings result (one row per report) and each day's previews."""
    rows = [{"date": day, "ticker": r["ticker"], "kind": "result", "report_date": r["date"],
             "eps_est": r["eps_est"], "eps": r["eps"], "surprise_pct": r["surprise"],
             "reaction_pct": round(r["reaction"], 2) if r["reaction"] is not None else None,
             "implied_pct": None, "avg_move_pct": None} for r in er["results"]]
    rows += [{"date": day, "ticker": p["ticker"], "kind": "preview", "report_date": p["date"],
              "eps_est": p["eps_est"], "eps": None, "surprise_pct": None, "reaction_pct": None,
              "implied_pct": round(p["implied"]["pct"], 2) if p["implied"] else None,
              "avg_move_pct": round(p["avg_move"], 2) if p["avg_move"] is not None else None}
             for p in er["previews"]]
    if rows:
        os.makedirs(DATA, exist_ok=True)
        _upsert("earnings", rows, day)


def last_valued():
    """{ticker: date of its most recent deep dive}."""
    path = os.path.join(DATA, "valuations.csv")
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path, dtype={"date": str})
    return df.groupby("ticker")["date"].max().to_dict()


def load_letters():
    if not os.path.exists(LETTERS):
        return []
    with open(LETTERS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def recent_letters(before, n=5):
    """The last n saved letters before market day `before`, newest first."""
    return [e for e in reversed(load_letters()) if e["date"] < before and e.get("take")][:n]


def recent_portfolio(before, n=10):
    path = os.path.join(DATA, "portfolio.csv")
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, dtype={"date": str})
    return df[df["date"] < before].tail(n).to_dict("records")
