"""Earnings mode: previews for holdings reporting soon, and results for those that just did.

Preview: consensus EPS and revenue, the options market's implied move (an at-the-money
straddle on the first expiry after the report, divided by the share price), and the stock's
average absolute move after its recent reports. The implied move is only shown when that
expiry falls within a week of the report; further out, ordinary volatility swamps the event.

Results: reported EPS vs the estimate and the stock's move on the reaction day (the report
day if it came before the close, otherwise the next trading day).
"""
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

PREVIEW_DAYS = 7     # show a preview when a holding reports within this many days
RESULTS_DAYS = 4     # show results for reports within the past this many days
MAX_EXPIRY_GAP = 7   # days between the report and the options expiry used for the implied move
PAST_REPORTS = 4


def _reaction_day(reported, closes):
    """The trading day whose close first reflects a report made at `reported`."""
    day = pd.Timestamp(reported.date())
    after_close = reported.hour >= 16
    later = closes.index[closes.index > day] if after_close else closes.index[closes.index >= day]
    return later[0] if len(later) else None


def _move_on(day, closes):
    i = closes.index.get_loc(day)
    return (float(closes.iloc[i]) / float(closes.iloc[i - 1]) - 1) * 100 if i else None


def implied_move(t, report_date, price):
    """Implied +/- move in percent from the at-the-money straddle, or None."""
    try:
        expiries = [e for e in t.options if datetime.fromisoformat(e).date() >= report_date]
    except Exception:
        return None
    if not expiries:
        return None
    expiry = expiries[0]
    if (datetime.fromisoformat(expiry).date() - report_date).days > MAX_EXPIRY_GAP:
        return None
    chain = t.option_chain(expiry)

    def mid(df):
        row = df.iloc[(df["strike"] - price).abs().argmin()]
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        return (bid + ask) / 2 if bid > 0 and ask > 0 else float(row.get("lastPrice") or 0)

    straddle = mid(chain.calls) + mid(chain.puts)
    return {"pct": straddle / price * 100, "expiry": expiry} if straddle > 0 else None


def scan(tickers, closes, today=None):
    """Earnings previews and results for `tickers`.

    closes: {ticker: daily close series} (about a year of history).
    """
    today = today or datetime.now().date()
    previews, results = [], []
    for tk in tickers:
        t = yf.Ticker(tk)
        try:
            dates = t.earnings_dates
        except Exception:
            continue
        if dates is None or dates.empty or tk not in closes:
            continue
        s = closes[tk]
        price = float(s.iloc[-1])
        past = dates[dates["Reported EPS"].notna()].sort_index()
        upcoming = dates[dates["Reported EPS"].isna()].sort_index()

        reactions = []
        for when in past.index[-PAST_REPORTS:]:
            day = _reaction_day(when.to_pydatetime(), s)
            move = _move_on(day, s) if day is not None else None
            if move is not None:
                reactions.append(move)

        upcoming = upcoming[[today <= d.date() <= today + timedelta(days=PREVIEW_DAYS)
                             for d in upcoming.index]]
        if len(upcoming):
            when = upcoming.index[0].to_pydatetime()
            est = {}
            for key, frame in (("eps", "earnings_estimate"), ("revenue", "revenue_estimate")):
                try:
                    est[key] = float(getattr(t, frame).loc["0q", "avg"])
                except Exception:
                    est[key] = None
            try:
                analysts = int(t.earnings_estimate.loc["0q", "numberOfAnalysts"])
            except Exception:
                analysts = None
            previews.append({
                "ticker": tk, "date": str(when.date()),
                "timing": "before the open" if when.hour < 12 else "after the close",
                "eps_est": est["eps"], "rev_est": est["revenue"], "analysts": analysts,
                "implied": implied_move(t, when.date(), price),
                "avg_move": sum(abs(m) for m in reactions) / len(reactions) if reactions else None,
                "past_moves": reactions,
            })

        for when, row in past.iterrows():
            if not (today - timedelta(days=RESULTS_DAYS) <= when.date() <= today):
                continue
            day = _reaction_day(when.to_pydatetime(), s)
            results.append({
                "ticker": tk, "date": str(when.date()),
                "eps_est": float(row["EPS Estimate"]) if pd.notna(row["EPS Estimate"]) else None,
                "eps": float(row["Reported EPS"]),
                "surprise": float(row["Surprise(%)"]) if pd.notna(row["Surprise(%)"]) else None,
                "reaction": _move_on(day, s) if day is not None else None,
                "reaction_day": str(day.date()) if day is not None else None,
            })
    previews.sort(key=lambda p: p["date"])
    return {"previews": previews, "results": results}
