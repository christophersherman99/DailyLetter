"""Daily Letter: a weekday market brief built around my portfolio, with adaptive market
movers, a world snapshot, risk analytics, and an AI-written take that remembers past
letters, sent to Gmail. Each day's numbers are saved to data/ (see history.py)."""
import csv
import io
import json
import logging
import os
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import quote
from zoneinfo import ZoneInfo

import anthropic
import feedparser
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

import dcf
import history
import regime
import risk
import shadow
import stress

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # funds have no earnings; keep quiet

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")

# Money market funds in portfolio.csv count as cash at $1.00 a share
CASH = {"SPAXX"}

WORLD = {
    "US": {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Russell 2000": "^RUT"},
    "Europe": {"Stoxx 600": "^STOXX", "FTSE 100": "^FTSE", "DAX": "^GDAXI"},
    "Asia": {"Nikkei 225": "^N225", "Hang Seng": "^HSI", "Kospi": "^KS11"},
}
FUTURES = {"S&P 500": "ES=F", "Nasdaq 100": "NQ=F"}
MACRO = {"US 10Y yield": "^TNX", "VIX": "^VIX", "Dollar index": "DX-Y.NYB",
         "EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X", "Gold": "GC=F", "WTI crude": "CL=F"}
SECTORS = {"Tech": "XLK", "Financials": "XLF", "Health care": "XLV",
           "Cons. discretionary": "XLY", "Communication": "XLC", "Industrials": "XLI",
           "Cons. staples": "XLP", "Energy": "XLE", "Utilities": "XLU",
           "Real estate": "XLRE", "Materials": "XLB"}
RISK_FREE = "^IRX"  # 13-week T-bill yield, for the Sharpe ratio
NEWS_FEEDS = {
    "Markets": "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
}
# Big macro dates. Earnings dates for your holdings are pulled automatically.
MANUAL_EVENTS = [
    {"date": "2026-10-28", "event": "Fed rate decision (FOMC)"},
    {"date": "2026-12-09", "event": "Fed rate decision (FOMC)"},
]

MOVER_MIN_CAP = 10e9   # adaptive movers: only companies worth $10B or more
MOVER_MIN_MOVE = 3     # ...that moved at least this many percent
MOVERS_PER_SIDE = 4
US_EXCHANGES = ["NYQ", "NMS", "NGM", "NCM", "ASE"]  # NYSE and Nasdaq, no over-the-counter
HOLDING_NEWS_MOVE = 2  # pull a headline for a holding that moved at least this many percent
UNUSUAL_Z = 2          # flag a move this many times bigger than the stock's normal day
CALENDAR_DAYS = 30
DEEP_DIVE_WEEKDAY = 0  # Monday: value one holding with a DCF (see dcf.py), rotating weekly
MODEL = "claude-opus-5-5"
DASHBOARD_URL = "https://christophersherman99.github.io/DailyLetter/"

# Look and feel
PAPER, CARD, INK, MUTED, FAINT = "#f3efe6", "#fffefb", "#1b1b1b", "#5f5b54", "#9b968c"
RULE, HAIR, ACCENT = "#e4ded2", "#efebe2", "#1d3557"
# Gains blue, losses orange: distinct for red-green color blindness (validated for
# protan, deutan, and tritan vision). Signs (+/-) always accompany the color too.
UP, DOWN, UP_BG, DOWN_BG = "#1f6fb2", "#c4560a", "#e4eef8", "#fbeadd"
AMBER = "#a86b00"
# No quotes inside these: they go inside style='...' attributes
SERIF = "Georgia,Times New Roman,serif"
SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"


# ---------- data ----------
def load_portfolio():
    # utf-8-sig drops a byte-order mark some editors and shells add to the start of the file
    with open(os.path.join(HERE, "portfolio.csv"), newline="", encoding="utf-8-sig") as f:
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
                for r in csv.DictReader(f)]
    return [{"ticker": r["ticker"].upper(), "shares": float(r["shares"]),
             "avg_cost": float(r["avg_cost"])} for r in rows if r.get("ticker")]


def _download(tickers):
    df = yf.download(tickers, period="1y", auto_adjust=True, group_by="ticker",
                     progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            s = df[t]["Close"].dropna()
        except KeyError:
            continue
        if len(s) >= 2:
            out[t] = s
    return out


def download(tickers):
    """A year of daily closes for every ticker in one batched request, retrying misses once."""
    tickers = sorted(set(tickers))
    data = _download(tickers)
    missing = [t for t in tickers if t not in data]
    if missing:
        data.update(_download(missing))
    for t in tickers:
        if t not in data:
            print("No data for", t)
    return data


def stats(s, ticker=""):
    if len(s) > 2 and s.iloc[-1] == s.iloc[-2]:
        s = s.iloc[:-1]  # Yahoo sometimes adds a placeholder row that repeats the last close
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    rets = s.pct_change().dropna()
    vol = float(rets.iloc[-61:-1].std()) * 100 if len(rets) > 20 else 0.0
    prior_years = s[s.index.year < s.index[-1].year]
    base = float(prior_years.iloc[-1]) if len(prior_years) else float(s.iloc[0])
    day = (last / prev - 1) * 100
    q = {"last": last, "prev": prev, "day": day, "ytd": (last / base - 1) * 100,
         "d5": (last / float(s.iloc[-6]) - 1) * 100 if len(s) > 5 else 0.0,
         "z": day / vol if vol else 0.0, "date": s.index[-1].date()}
    if ticker == "^TNX":
        scale = 10 if last > 20 else 1
        q.update(last=last / scale, bps=(last - prev) / scale * 100,
                 ytd_bps=(last - base) / scale * 100)
    return q


def screen_movers():
    """Large US companies with the biggest moves in the latest session."""
    Q = yf.EquityQuery
    out = {}
    for side, op, threshold, asc in (("up", "gt", MOVER_MIN_MOVE, False),
                                     ("down", "lt", -MOVER_MIN_MOVE, True)):
        try:
            query = Q("and", [Q("eq", ["region", "us"]),
                              Q("is-in", ["exchange", *US_EXCHANGES]),
                              Q("gte", ["intradaymarketcap", MOVER_MIN_CAP]),
                              Q(op, ["percentchange", threshold])])
            res = yf.screen(query, sortField="percentchange", sortAsc=asc,
                            size=MOVERS_PER_SIDE)
            out[side] = [{"ticker": r["symbol"], "name": r.get("shortName") or r["symbol"],
                          "day": r["regularMarketChangePercent"],
                          "cap": r.get("marketCap", 0)} for r in res.get("quotes", [])]
        except Exception as e:
            print("Screener failed:", e)
            out[side] = []
    return out


def ticker_headline(ticker, name="", max_age_days=3):
    """A recent Yahoo Finance headline for a ticker, preferring ones that name the company."""
    keys = {ticker.lower()} | ({name.split()[0].strip(",.").lower()} if name else set())
    recent = []
    try:
        for item in yf.Ticker(ticker).news[:10]:
            c = item["content"]
            published = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - published > timedelta(days=max_age_days):
                continue
            link = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url", "")
            recent.append((c["title"], link))
    except Exception:
        return None
    named = [h for h in recent if any(k in h[0].lower() for k in keys)]
    return (named or recent or [None])[0]


def market_headlines(n=4):
    out = {}
    for label, url in NEWS_FEEDS.items():
        try:
            out[label] = [(e.title, e.link) for e in feedparser.parse(url).entries[:n]]
        except Exception:
            out[label] = []
    return out


def calendar(holdings):
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=CALENDAR_DAYS)
    events = []
    for h in holdings:
        if h["ticker"] in CASH:
            continue
        try:
            d = yf.Ticker(h["ticker"]).calendar.get("Earnings Date", [None])[0]
            if d and today <= d <= horizon:
                events.append((d, f"{h['ticker']} earnings"))
        except Exception:
            pass
    for e in MANUAL_EVENTS:
        d = date.fromisoformat(e["date"])
        if today <= d <= horizon:
            events.append((d, e["event"]))
    return sorted(events)


def deep_dive(holdings, rf):
    """Monday's DCF on one holding: whichever stock was valued longest ago (never-valued
    first). Funds and banks are skipped by dcf.run. Set DEEP_DIVE=1 to force it on another
    day, or DEEP_DIVE=TICKER to value a specific company."""
    forced = os.environ.get("DEEP_DIVE", "").upper()
    if not forced and datetime.now(ET).weekday() != DEEP_DIVE_WEEKDAY:
        return None
    if forced and forced not in ("1", "TRUE", "YES"):
        order = [forced]
    else:
        last = history.last_valued()
        order = sorted((h["ticker"] for h in holdings if h["ticker"] not in CASH),
                       key=lambda t: (last.get(t, ""), t))
    for ticker in order:
        try:
            v = dcf.run(ticker, rf)
        except Exception as e:
            print("DCF failed for", ticker, e)
            continue
        if v.get("skipped"):
            print("DCF skipped", ticker, "-", v["skipped"])
        else:
            return v
    return None


# ---------- portfolio ----------
def portfolio_view(holdings, data):
    rows, missing = [], []
    for h in holdings:
        t, shares = h["ticker"], h["shares"]
        if t in CASH:
            price = prev = 1.0
            z = 0.0
        elif t in data:
            q = stats(data[t])
            price, prev, z = q["last"], q["prev"], q["z"]
        else:
            missing.append(t)
            continue
        rows.append({"ticker": t, "shares": shares, "price": price, "cash": t in CASH,
                     "value": shares * price, "day_usd": shares * (price - prev),
                     "day": (price / prev - 1) * 100, "z": z,
                     "cost": shares * h["avg_cost"],
                     "since_bought": (price / h["avg_cost"] - 1) * 100})
    value = sum(r["value"] for r in rows)
    day_usd = sum(r["day_usd"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / value * 100
    rows.sort(key=lambda r: -r["value"])

    # Value of today's holdings over the past year (as if held the whole time)
    invested = [r for r in rows if not r["cash"]]
    frame = pd.DataFrame({r["ticker"]: data[r["ticker"]] * r["shares"] for r in invested})
    history_1y = frame.ffill().dropna().sum(axis=1)
    history_1y += sum(r["value"] for r in rows if r["cash"])

    return {"rows": rows, "value": value, "day_usd": day_usd,
            "day": day_usd / (value - day_usd) * 100, "cost": cost,
            "gain_usd": value - cost, "gain": (value / cost - 1) * 100,
            "history_1y": history_1y, "history": history_1y.iloc[-63:],
            "prices": {r["ticker"]: data[r["ticker"]] for r in invested},
            "missing": missing}


# ---------- AI take ----------
TAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "take": {"type": "string"},
        "portfolio": {"type": "string"},
        "watch": {"type": "array", "items": {"type": "string"}},
        "deep_dive": {"type": "string"},
    },
    "required": ["take", "portfolio", "watch", "deep_dive"],
    "additionalProperties": False,
}
SYSTEM = """You write the AI sections of a short weekday morning market letter. The reader is \
a college student interested in global markets, prime brokerage and Asia, who owns the \
portfolio shown in the data.

Fill three fields:
- take: 3 to 5 sentences on what drove markets in the latest session across the US, Europe \
and Asia. Lead with the most important thing. Connect moves across regions, sectors and \
asset classes where the data supports it.
- portfolio: 1 to 2 sentences explaining the portfolio's move: which holdings drove it and \
why, and how it compared with the S&P 500.
- watch: 2 or 3 short items worth watching today, drawn only from the calendar, futures, \
and headlines provided.
- deep_dive: only when the data includes a DEEP DIVE valuation, 2 to 3 sentences that \
explain the gap between the model value and the share price. Compare the growth the price \
implies (reverse DCF) with the analyst growth used, and name what a simple DCF holds flat \
that the market may be paying for, such as margin expansion. Treat the model as one lens, \
not a verdict. Otherwise an empty string.

You also get a rules-based market regime, stress tests, 5-day changes, the portfolio's \
risk stats, and your previous letters. Mention the regime only when it changed, a signal \
just flipped, or it explains the day. The shadow portfolio is the reader's own benchmark: \
you may note a meaningful gap with the real portfolio, but never suggest switching to it \
or making any trade. Use them \
to add continuity: note a theme that has carried over several days, or a meaningful shift \
in risk, when the data clearly shows it. Do not repeat earlier letters' wording, and do not \
force a callback when nothing carries over.

Privacy: your text is also saved to a public record. Describe the reader's own portfolio \
and holdings only in percentages, never in dollars (share prices and market figures are fine).

Rules: use only the numbers, events and headlines in the data. Never invent figures or \
causes. When a cause is inferred from headlines rather than stated, say "likely". Do not give \
buy, sell or hold recommendations. Plain, specific language. No hype, no em dashes, no \
bullet characters inside the strings."""


def ai_take(brief):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    client = anthropic.Anthropic()
    try:
        r = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": TAKE_SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": brief}],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        print("AI take skipped:", e)
        return None
    if r.stop_reason != "end_turn":
        print("AI take skipped, stop reason:", r.stop_reason)
        return None
    try:
        return json.loads(next(b.text for b in r.content if b.type == "text"))
    except (StopIteration, json.JSONDecodeError) as e:
        print("AI take unreadable:", e)
        return None


def build_brief(port, world, futures, macro, sectors, movers, mover_news,
                holding_news, news, events, risk=None, exposure=None, corr=None,
                past_letters=(), past_days=(), valuation=None, weather=None,
                stress_tests=None, shadows=()):
    """Everything the AI sees, as compact plain text."""
    # Percentages only: the AI's text is saved to the public record
    start_value = port["value"] - port["day_usd"]
    L = [f"Date: {datetime.now(ET):%A %B %d, %Y}", "",
         f"PORTFOLIO: today {port['day']:+.2f}%, S&P 500 "
         f"{world['US']['S&P 500']['day']:+.2f}%, gain since purchase {port['gain']:+.1f}%",
         "  (contribution = percentage points of the portfolio's move from that holding)"]
    for r in port["rows"]:
        if not r["cash"]:
            flag = " UNUSUAL MOVE" if abs(r["z"]) >= UNUSUAL_Z else ""
            L.append(f"  {r['ticker']}: {r['day']:+.2f}% (contribution "
                     f"{r['day_usd'] / start_value * 100:+.2f} pts), "
                     f"{r['weight']:.0f}% of portfolio{flag}")
    for t, (title, _) in holding_news.items():
        L.append(f"  News {t}: {title}")
    if risk:
        L.append(f"RISK (today's holdings, past year): beta {risk['beta']:.2f}, volatility "
                 f"{risk['vol']:.1f}% vs S&P {risk['spx_vol']:.1f}%, 1-year return "
                 f"{risk['ret_1y']:+.1f}% vs S&P {risk['spx_ret_1y']:+.1f}%, Sharpe "
                 f"{risk['sharpe']:.2f} vs S&P {risk['spx_sharpe']:.2f}, 1-in-20 day loss "
                 f"{risk['var_pct']:.2f}%, {risk['off_peak']:.1f}% from peak")
    if exposure:
        L.append("SECTOR EXPOSURE (vs S&P): " + ", ".join(
            f"{s} {w:.0f}% ({w - exposure['benchmark'].get(s, 0):+.0f})"
            for s, w in list(exposure["sectors"].items())[:6]))
        L.append("REGIONS: " + ", ".join(f"{k} {v:.0f}%" for k, v in exposure["regions"].items()))
    if corr:
        c, a, b = corr["most"]
        L.append(f"MOST CORRELATED HOLDINGS: {a} and {b} ({c:.2f})")
    if past_days:
        L.append("PORTFOLIO RECENT DAYS: " + ", ".join(
            f"{d['date']} {d['day_pct']:+.2f}%" for d in past_days))
    L.append("\nWORLD (day / 5 days / year to date):")
    for region, rows in world.items():
        for name, q in rows.items():
            L.append(f"  {region} {name} [{q['date']:%b %d}]: {q['day']:+.2f}% / "
                     f"{q['d5']:+.1f}% / {q['ytd']:+.1f}%")
    L.append("US futures now: " + ", ".join(f"{n} {q['day']:+.2f}%" for n, q in futures.items()))
    L.append("\nSECTORS (day / 5 days): " + ", ".join(
        f"{n} {q['day']:+.2f}% / {q['d5']:+.1f}%" for n, q in sectors.items()))
    L.append("\nRATES, FX, COMMODITIES:")
    for name, q in macro.items():
        if "bps" in q:
            L.append(f"  {name}: {q['last']:.2f}% ({q['bps']:+.0f} bps)")
        else:
            L.append(f"  {name}: {q['last']:,.2f} ({q['day']:+.2f}%)")
    L.append("\nBIGGEST LARGE-CAP MOVERS:")
    for m in movers["up"] + movers["down"]:
        head = mover_news.get(m["ticker"])
        L.append(f"  {m['ticker']} ({m['name']}): {m['day']:+.1f}%"
                 + (f" | {head[0]}" if head else ""))
    L.append("\nHEADLINES:")
    L += [f"  {t}" for items in news.values() for t, _ in items]
    L.append("\nCOMING UP:")
    L += [f"  {d:%a %b %d}: {e}" for d, e in events] or ["  nothing scheduled"]
    if weather:
        L.append(f"\nMARKET REGIME: {weather['name']} (score {weather['score']} of "
                 f"{weather['max']}; 0 ok, 1 caution, 2 stress per signal)")
        L += [f"  {s['name']} [{('ok', 'caution', 'stress')[s['level']]}]: "
              f"{s['reading'].replace('&amp;', '&')}" for s in weather["signals"]]
    if stress_tests:
        L.append("\nSTRESS TESTS on today's holdings:")
        L += [f"  {x['name']}: {x['pct']:+.1f}% vs S&P {x['spx_pct']:+.1f}%"
              for x in stress_tests["replays"]]
        L += [f"  {x['name']} (via 1-year beta): {x['pct']:+.1f}%"
              for x in stress_tests["shocks"]]
        if stress_tests["ai"]:
            L.append(f"  AI and big-tech exposure incl. funds: {stress_tests['ai']['pct']:.0f}%")
    for sh in shadows:
        mix = ", ".join(f"{t} {w:.0%}" for t, w in sh["weights"].items())
        L.append(f"\nSHADOW PORTFOLIO '{sh['name']}' ({mix}), paper-tracked since "
                 f"{sh['since']}: {sh['since_pct']:+.2f}% vs real portfolio "
                 f"{sh['you_since_pct']:+.2f}%")
        if sh["risk"]:
            r = sh["risk"]
            L.append(f"  Risk (past year): beta {r['beta']:.2f}, volatility {r['vol']:.1f}%, "
                     f"1-year return {r['ret_1y']:+.1f}%, Sharpe {r['sharpe']:.2f}, "
                     f"worst drop {r['max_dd']:.1f}%")
        if sh["ai"]:
            L.append(f"  AI and big-tech exposure: {sh['ai']['pct']:.0f}%")
    if valuation:
        L.append("\nDEEP DIVE (DCF model):\n" + dcf.report(valuation))
    if past_letters:
        L.append("\nYOUR PREVIOUS LETTERS (newest first):")
        L += [f"  {e['date']}: {e['take']}" for e in past_letters]
    return "\n".join(L)


# ---------- charts ----------
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"],
    "axes.edgecolor": RULE, "xtick.color": FAINT, "ytick.color": FAINT,
})


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=CARD)
    plt.close(fig)
    return buf.getvalue()


def _bare(ax):
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_facecolor(CARD)
    ax.tick_params(length=0, labelsize=9)


SHADOW_COLOR = "#b5835a"


def perf_chart(port, sp500, shadows=()):
    """Portfolio vs S&P 500 (and the first shadow portfolio), % return over 3 months."""
    hist = port["history"]
    spx = sp500.reindex(hist.index).ffill()
    fig, ax = plt.subplots(figsize=(6, 2.3), dpi=200)
    for sh in shadows[:1]:
        s = sh["history"].reindex(hist.index).ffill().dropna()
        ret = (s / s.iloc[0] - 1) * 100
        ax.plot(ret.index, ret.values, color=SHADOW_COLOR, linewidth=1.3, linestyle=(0, (4, 2)))
        ax.plot(ret.index[-1], ret.iloc[-1], "o", color=SHADOW_COLOR, markersize=3.5)
    _bare(ax)
    for s, color, width in ((spx, "#bdb6a8", 1.3), (hist, ACCENT, 1.9)):
        ret = (s / s.iloc[0] - 1) * 100
        ax.plot(ret.index, ret.values, color=color, linewidth=width, solid_capstyle="round")
        ax.plot(ret.index[-1], ret.iloc[-1], "o", color=color, markersize=3.5)
        if s is hist:
            ax.fill_between(ret.index, ret.values, 0, color=ACCENT, alpha=0.06, linewidth=0)
    ax.axhline(0, color=RULE, linewidth=0.8, zorder=0)
    ax.yaxis.tick_right()
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    ax.grid(axis="y", color=HAIR, linewidth=0.6)
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))
    ax.margins(x=0.01)
    fig.tight_layout(pad=0.4)
    return _png(fig)


def sector_chart(sectors):
    items = sorted(sectors.items(), key=lambda kv: kv[1]["day"])
    names = [n for n, _ in items]
    vals = [q["day"] for _, q in items]
    fig, ax = plt.subplots(figsize=(6, 3.1), dpi=200)
    _bare(ax)
    ax.barh(names, vals, height=0.58, color=[UP if v >= 0 else DOWN for v in vals], alpha=0.85)
    ax.axvline(0, color=FAINT, linewidth=0.7)
    span = max(abs(v) for v in vals) or 1
    for i, v in enumerate(vals):
        ax.text(v + span * (0.03 if v >= 0 else -0.03), i, f"{v:+.1f}%", va="center",
                ha="left" if v >= 0 else "right", fontsize=8.5, color=MUTED)
    ax.set_xlim(-span * 1.3, span * 1.3)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=9.5, labelcolor=INK)
    fig.tight_layout(pad=0.4)
    return _png(fig)


# ---------- email ----------
NUM = f"font-family:{SANS};font-variant-numeric:tabular-nums"
DOT = " &middot; "


def signed(x, fmt="{:+.2f}%"):
    return f"<span style='color:{UP if x >= 0 else DOWN}'>{fmt.format(x)}</span>"


def money(x, digits=2):
    return f"{'+' if x >= 0 else '-'}${abs(x):,.{digits}f}"


def signed_money(x, digits=2):
    return f"<span style='color:{UP if x >= 0 else DOWN}'>{money(x, digits)}</span>"


def chip(text, x):
    fg, bg = (UP, UP_BG) if x >= 0 else (DOWN, DOWN_BG)
    return (f"<span style='background:{bg};color:{fg};padding:2px 8px;border-radius:10px;"
            f"{NUM};font-size:13px;font-weight:600;white-space:nowrap'>{text}</span>")


def link(title, url, size=15):
    return (f"<a href='{escape(url)}' style='color:{INK};text-decoration:none;"
            f"border-bottom:1px solid {RULE};font-family:{SERIF};font-size:{size}px;"
            f"line-height:1.45'>{escape(title)}</a>")


def dash(query="", anchor=""):
    """A link into the dashboard, opened at the matching section (see applyDeepLink in
    site/app.js)."""
    return DASHBOARD_URL + (f"?{query}" if query else "") + (f"#{anchor}" if anchor else "")


def label(text, top=True, link=None):
    rule = f"border-top:1px solid {RULE};padding-top:20px;margin-top:30px;" if top else ""
    explore = (f"<a href='{escape(link)}' style='float:right;color:{ACCENT};text-decoration:none;"
               "font-weight:600;letter-spacing:.3px;text-transform:none;font-size:11.5px'>"
               "Explore &rarr;</a>" if link else "")
    return (f"<div style='{rule}font-family:{SANS};font-size:11px;font-weight:700;"
            f"letter-spacing:1.6px;text-transform:uppercase;color:{ACCENT};"
            f"margin-bottom:12px'>{explore}{text}</div>")


def caption(html):
    return (f"<div style='font-family:{SANS};font-size:12px;color:{MUTED};"
            f"margin:18px 0 6px'>{html}</div>")


def th(text, align="right"):
    pad = "0 0 6px 10px" if align == "right" else "0 0 6px"
    return (f"<td style='text-align:{align};padding:{pad};font-family:{SANS};font-size:10px;"
            f"letter-spacing:1px;text-transform:uppercase;color:{FAINT};"
            f"border-bottom:1px solid {RULE}'>{text}</td>")


def td(html, align="right", extra=""):
    pad = "8px 0 8px 10px" if align == "right" else "8px 0"
    return (f"<td style='text-align:{align};padding:{pad};border-bottom:1px solid {HAIR};"
            "white-space:nowrap;"
            f"{NUM};font-size:13.5px;color:{INK};{extra}'>{html}</td>")


TABLE = "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>"


def tile(name, value, sub):
    return (f"<td width='33%' style='padding:4px;vertical-align:top'>"
            f"<div style='background:{PAPER};border:1px solid {RULE};padding:10px 10px 9px'>"
            f"<div style='font-family:{SANS};font-size:9.5px;font-weight:700;letter-spacing:1px;"
            f"text-transform:uppercase;color:{MUTED}'>{name}</div>"
            f"<div style='font-family:{SERIF};font-size:21px;color:{INK};margin:4px 0 2px'>{value}</div>"
            f"<div style='{NUM};font-size:11px;color:{MUTED}'>{sub}</div></div></td>")


def weather_html(w):
    color = {"Calm": UP, "Mixed": AMBER, "Stressed": DOWN}[w["name"]]
    dots = (UP, AMBER, DOWN)
    shapes = ("&#9679;", "&#9650;", "&#9632;")  # ok, caution, stress: readable without color
    p = [label("Market Weather", link=dash(anchor="today")),
         f"<div style='font-family:{SERIF};font-size:26px;color:{color};line-height:1.1'>"
         f"{w['name']}<span style='font-family:{SANS};font-size:12.5px;color:{MUTED}'>"
         f"&nbsp;&nbsp;{w['flags']} of {len(w['signals'])} signals flagged &nbsp;"
         f"<span style='color:{FAINT}'>&#9679; ok &nbsp;&#9650; caution &nbsp;&#9632; stress"
         f"</span></span></div>",
         f"<div style='height:8px'></div>{TABLE}"]
    for s in w["signals"]:
        why = (f"<div style='font-family:{SANS};font-size:11.5px;color:{FAINT};line-height:1.45;"
               f"white-space:normal;margin-top:2px'>{s['why']}</div>" if s["level"] else "")
        p.append(f"<tr><td style='width:16px;padding:7px 0;vertical-align:top;color:{dots[s['level']]};"
                 f"font-size:12px;border-bottom:1px solid {HAIR}'>{shapes[s['level']]}</td>"
                 + td(f"<b>{s['name']}</b>", "left", "width:92px;vertical-align:top")
                 + td(f"{s['reading']}{why}", "left",
                      f"white-space:normal;color:{MUTED};font-size:13px;vertical-align:top")
                 + "</tr>")
    p.append("</table>")
    return "".join(p)


def stress_html(st):
    p = [caption("Stress tests: what today's holdings would have done")]
    p.append(f"{TABLE}<tr>{th('Scenario', 'left')}{th('You')}{th('$')}{th('S&amp;P')}</tr>")
    for x in st["replays"]:
        p.append(f"<tr>{td(x['name'], 'left', 'white-space:normal')}"
                 f"{td(signed(x['pct'], '{:+.1f}%'))}{td(signed_money(x['usd'], 0))}"
                 f"{td(signed(x['spx_pct'], '{:+.1f}%'))}</tr>")
    for x in st["shocks"]:
        name = f"{x['name']} <span style='color:{FAINT}'>(hypothetical)</span>"
        p.append(f"<tr>{td(name, 'left', 'white-space:normal')}"
                 f"{td(signed(x['pct'], '{:+.1f}%'))}{td(signed_money(x['usd'], 0))}{td('')}</tr>")
    p.append("</table>")
    if st["shocks"]:
        p.append(f"<div style='font-family:{SANS};font-size:11px;color:{FAINT};margin-top:6px;"
                 "line-height:1.5'>Hypothetical rows scale each holding by how much it moved "
                 "with that factor over the past year. A real AI selloff would likely pull the "
                 "whole market down too, so the S&amp;P row is the better guide to a bad case."
                 "</div>")
    ai = st.get("ai")
    if ai:
        merged = {}
        for sym, v in ai["names"]:
            key = {"GOOG": "GOOGL"}.get(sym, sym)
            merged[key] = merged.get(key, 0) + v
        top = ", ".join(sym for sym, _ in sorted(merged.items(), key=lambda kv: -kv[1])[:4])
        p.append(f"<div style='{NUM};font-size:12.5px;color:{MUTED};margin-top:10px;"
                 f"line-height:1.6'>AI and big-tech exposure: <b style='color:{INK}'>"
                 f"{ai['pct']:.0f}%</b> of your money (${ai['usd']:,.0f}), mostly {top}. "
                 "Counts what your funds hold.</div>")
    return "".join(p)


def risk_html(risk, exposure, corr, stress_tests=None):
    p = [label("Risk Check", link=dash(anchor="portfolio"))]
    if risk:
        tiles = [
            tile("Beta", f"{risk['beta']:.2f}", "S&amp;P = 1.00"),
            tile("Volatility", f"{risk['vol']:.0f}%", f"S&amp;P {risk['spx_vol']:.0f}%"),
            tile("Bad day", f"-${risk['var_usd']:,.0f}", "1-in-20 day loss"),
            tile("1-year return", signed(risk["ret_1y"], "{:+.1f}%"),
                 f"S&amp;P {risk['spx_ret_1y']:+.1f}%"),
            tile("Sharpe ratio", f"{risk['sharpe']:.2f}", f"S&amp;P {risk['spx_sharpe']:.2f}"),
            tile("From peak", f"{risk['off_peak']:.1f}%", f"Worst {risk['max_dd']:.1f}%"),
        ]
        p.append(f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
                 f"style='border-collapse:collapse;margin:0 -4px'><tr>{''.join(tiles[:3])}</tr>"
                 f"<tr>{''.join(tiles[3:])}</tr></table>")
    if exposure:
        p.append(caption("Where your money really is, looking inside your funds"))
        p.append(f"{TABLE}<tr>{th('Sector', 'left')}{th('', 'left')}{th('You')}{th('vs S&amp;P')}</tr>")
        shown = [(s, w) for s, w in exposure["sectors"].items() if s != "Cash"][:6]
        for s, w in shown:
            diff = w - exposure["benchmark"].get(s, 0)
            bar = (f"<span style='display:inline-block;width:{w * 2.2:.0f}px;height:6px;"
                   f"background:{ACCENT};opacity:.55;border-radius:2px'></span>")
            p.append(f"<tr>{td(s, 'left')}{td(bar, 'left', 'width:45%')}{td(f'{w:.0f}%')}"
                     f"{td(signed(diff, '{:+.0f} pts') if exposure['benchmark'] else '')}</tr>")
        p.append("</table>")
        regions = DOT.join(f"{k} {v:.0f}%" for k, v in exposure["regions"].items() if v >= 0.5)
        p.append(f"<div style='{NUM};font-size:12.5px;color:{MUTED};margin-top:8px'>"
                 f"Regions: {regions}</div>")
        if exposure["top"]:
            p.append(caption("Your biggest companies, counting what your funds hold"))
            p.append(TABLE)
            for c in exposure["top"]:
                how = ", ".join("your shares" if v == "shares" else v for v in c["via"])
                name = (f"<b>{escape(c['name'])}</b><br><span style='font-size:11.5px;"
                        f"color:{MUTED}'>via {how}</span>")
                p.append(f"<tr>{td(name, 'left', 'white-space:normal')}"
                         f"{td(f'${c['value']:,.0f}')}{td(f'{c['pct']:.1f}%')}</tr>")
            p.append("</table>")
    if corr:
        c, a, b = corr["most"]
        lc, la, lb = corr["least"]
        p.append(f"<div style='{NUM};font-size:12.5px;color:{MUTED};margin-top:10px;line-height:1.6'>"
                 f"Move most alike: <b style='color:{INK}'>{a} &amp; {b}</b> ({c:.2f}). "
                 f"Most independent: <b style='color:{INK}'>{la} &amp; {lb}</b> ({lc:.2f}).</div>")
    if stress_tests:
        p.append(stress_html(stress_tests))
    return "".join(p)


def deep_dive_html(v, note):
    b = lambda x: f"${x / 1e9:,.0f}B" if x >= 1e10 else f"${x / 1e9:,.1f}B"
    ig = v["implied_growth"]
    p = [label(f"Deep Dive &middot; {escape(v['name'])}",
               link=dash(f"dcf={quote(v['ticker'])}", "valuation"))]
    if ig is not None:
        p.append(f"<div style='font-family:{SERIF};font-size:18px;line-height:1.5;color:{INK}'>"
                 f"Today's price implies <b>{ig:.1%}</b> revenue growth a year for "
                 f"{dcf.YEARS} years. Analysts expect {v['growth'][0]:.1%} this year and "
                 f"{v['growth'][1]:.1%} next.</div>")
    tiles = [tile("Share price", f"${v['price']:,.2f}", v["ticker"]),
             tile("DCF value", f"${v['per_share']:,.0f}",
                  f"{signed(v['upside'] * 100, '{:+.0f}%')} vs price"),
             tile("Discount rate", f"{v['wacc']:.1%}", "WACC")]
    p.append(f"<div style='height:12px'></div><table role='presentation' width='100%' "
             f"cellpadding='0' cellspacing='0' style='border-collapse:collapse;margin:0 -4px'>"
             f"<tr>{''.join(tiles)}</tr></table>")
    if note:
        p.append(f"<div style='font-family:{SERIF};font-style:italic;font-size:15px;"
                 f"line-height:1.55;color:#3d3a35;margin-top:14px;padding-left:12px;"
                 f"border-left:2px solid {RULE}'>{escape(note)}</div>")

    p.append(caption("Key assumptions"))
    rows = [
        (f"Revenue (FY{v['fiscal_year']})", b(v["revenue"])),
        ("Growth, years 1 and 2", f"{v['growth'][0]:.1%}, {v['growth'][1]:.1%} "
                                   f"({v['growth_source']})"),
        (f"Growth, years 3 to {dcf.YEARS}", f"fades to {v['terminal_growth']:.1%}"),
        ("Free cash flow margin", f"{v['fcf_margin']:.1%} (3-year median)"),
        ("Cost of equity", f"{v['cost_of_equity']:.1%} = {v['rf']:.2%} 10Y + "
                           f"{v['beta']:.2f} beta &times; {dcf.EQUITY_RISK_PREMIUM:.0%}"),
        ("Terminal value share", f"{v['terminal_share']:.0%} of enterprise value"),
    ]
    p.append(TABLE + "".join(f"<tr>{td(k, 'left', f'color:{MUTED}')}{td(val)}</tr>"
                             for k, val in rows) + "</table>")

    p.append(caption("Value per share if the discount rate or long-run growth differ. "
                     "Blue is above today's price."))
    head = "".join(f"<td style='text-align:center;padding:5px 2px;{NUM};font-size:10.5px;"
                   f"color:{FAINT}'>{g:.1%}</td>" for g in v["grid_terminals"])
    p.append(f"{TABLE}<tr><td style='{NUM};font-size:9.5px;color:{FAINT};padding:5px 2px'>"
             f"WACC \\ growth</td>{head}</tr>")
    for i, (rate, row) in enumerate(zip(v["grid_rates"], v["grid"])):
        cells = []
        for j, val in enumerate(row):
            base = i == 2 and j == 2
            if val is None:
                bg, text = PAPER, "n/a"
            else:
                bg, text = (UP_BG if val >= v["price"] else DOWN_BG), f"${val:,.0f}"
            border = f"border:2px solid {INK}" if base else f"border:1px solid {CARD}"
            cells.append(f"<td style='text-align:center;padding:6px 2px;background:{bg};{border};"
                         f"{NUM};font-size:12.5px;color:{INK};"
                         f"font-weight:{700 if base else 400}'>{text}</td>")
        p.append(f"<tr><td style='{NUM};font-size:10.5px;color:{FAINT};padding:5px 2px'>"
                 f"{rate:.1%}</td>{''.join(cells)}</tr>")
    p.append("</table>")
    p.append(f"<div style='{NUM};font-size:11px;color:{FAINT};margin-top:8px'>Two-stage "
             f"unlevered free cash flow model, {dcf.YEARS}-year projection, Gordon growth "
             "terminal value. Full model: dcf.py.</div>")
    return "".join(p)


def _three_month(series, like):
    """Return over the same window as `like` (the 3-month portfolio history), in percent."""
    s = series.reindex(like.index).ffill().dropna()
    return (float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100


def shadow_html(sh, you_risk, you_stress):
    since = date.fromisoformat(sh["since"])
    mix = DOT.join(f"{t} {w:.0%}" for t, w in sh["weights"].items())
    p = [label(f"Shadow Portfolio &middot; {escape(sh['name'])}",
               link=dash(f"preset={quote(sh['name'])}", "simulator")),
         f"<div style='{NUM};font-size:12.5px;color:{MUTED};line-height:1.6'>{mix}</div>",
         f"<div style='{NUM};font-size:12px;color:{FAINT};margin:4px 0 12px'>Your par: "
         f"tracked on paper at your portfolio's value since {since:%b} {since.day}. "
         "A benchmark to measure against, not a recommendation.</div>",
         f"{TABLE}<tr>{th('', 'left')}{th('You')}"
         f"<td style='text-align:right;padding:0 0 6px 10px;font-family:{SANS};font-size:10px;"
         f"letter-spacing:1px;text-transform:uppercase;color:{SHADOW_COLOR};"
         f"border-bottom:1px solid {RULE}'>{escape(sh['name'])}</td></tr>"]

    def row(name, you, them):
        p.append(f"<tr>{td(name, 'left', f'color:{MUTED}')}{td(you)}{td(them)}</tr>")

    pct = lambda x, f="{:+.1f}%": signed(x, f) if x is not None else "&ndash;"
    row(f"Since {since:%b} {since.day}", pct(sh["you_since_pct"], "{:+.2f}%"),
        pct(sh["since_pct"], "{:+.2f}%"))
    r = sh["risk"]
    if r and you_risk:
        row("1-year return", pct(you_risk["ret_1y"]), pct(r["ret_1y"]))
        row("Volatility", f"{you_risk['vol']:.0f}%", f"{r['vol']:.0f}%")
        row("Beta", f"{you_risk['beta']:.2f}", f"{r['beta']:.2f}")
        row("Bad day (1 in 20)", f"-${you_risk['var_usd']:,.0f}", f"-${r['var_usd']:,.0f}")
        row("Worst drop, past year", f"{you_risk['max_dd']:.1f}%", f"{r['max_dd']:.1f}%")
        row("Sharpe ratio", f"{you_risk['sharpe']:.2f}", f"{r['sharpe']:.2f}")
    if sh["replays"] and you_stress:
        theirs = {x["name"]: x for x in sh["replays"]}
        for x in you_stress["replays"]:
            if x["name"] in theirs:
                row(x["name"], pct(x["pct"]), pct(theirs[x["name"]]["pct"]))
    if sh["ai"] and you_stress and you_stress.get("ai"):
        row("AI and big-tech exposure", f"{you_stress['ai']['pct']:.0f}%", f"{sh['ai']['pct']:.0f}%")
    p.append("</table>")
    return "".join(p)


def build_html(port, world, futures, macro, movers, mover_news, holding_news, news,
               events, ai, risk=None, exposure=None, corr=None, valuation=None,
               weather=None, stress_tests=None, shadows=None):
    now = datetime.now(ET)
    spx = world["US"]["S&P 500"]
    p = []

    # Masthead with a one-line market strip
    strip = []
    for name, q in (("S&P 500", spx), ("Nasdaq", world["US"].get("Nasdaq")),
                    ("Stoxx 600", world["Europe"].get("Stoxx 600")),
                    ("Nikkei", world["Asia"].get("Nikkei 225"))):
        if q:
            strip.append(f"{name} {signed(q['day'])}")
    if "US 10Y yield" in macro:
        strip.append(f"10Y {macro['US 10Y yield']['last']:.2f}%")
    p.append(f"<div style='font-family:{SANS};font-size:11px;letter-spacing:1.6px;"
             f"text-transform:uppercase;color:{MUTED}'>{now:%A, %B} {now.day}, {now.year}</div>"
             f"<div style='font-family:{SERIF};font-size:34px;line-height:1.15;color:{INK};"
             f"margin:6px 0 14px'>The Daily Letter</div>"
             f"<div style='border-top:3px double {INK}'></div>"
             f"<div style='{NUM};font-size:12px;color:{MUTED};padding:9px 0;"
             f"border-bottom:1px solid {RULE}'>{DOT.join(strip)}</div>"
             f"<div style='font-family:{SANS};font-size:12px;padding-top:8px'>"
             f"<a href='{DASHBOARD_URL}' style='color:{ACCENT};text-decoration:none'>"
             "Open the dashboard: simulator, valuation playground, history &rarr;</a></div>")

    if ai:
        p.append(label("The Take", top=False,
                       link=dash(f"letter={world['US']['S&P 500']['date']}", "letters"))
                 .replace("margin-bottom:12px", "margin:24px 0 10px"))
        p.append(f"<div style='font-family:{SERIF};font-size:17px;line-height:1.65;"
                 f"color:{INK}'>{escape(ai['take'])}</div>")

    if weather:
        p.append(weather_html(weather))

    # Portfolio
    p.append(label("Your Portfolio", link=dash(anchor="history")))
    p.append(f"<div style='font-family:{SERIF};font-size:36px;line-height:1.1;color:{INK}'>"
             f"${port['value']:,.2f}</div>"
             f"<div style='margin-top:10px;font-family:{SANS};font-size:13px;color:{MUTED}'>"
             f"{chip(f'{money(port['day_usd'])} &nbsp;{port['day']:+.2f}%', port['day'])}"
             f"&nbsp; today, vs. S&amp;P 500 {signed(spx['day'])}</div>"
             f"<div style='margin-top:8px;{NUM};font-size:13px;color:{MUTED}'>Since you bought: "
             f"{signed_money(port['gain_usd'], 0)} ({signed(port['gain'], '{:+.1f}%')})</div>")
    if ai:
        p.append(f"<div style='font-family:{SERIF};font-style:italic;font-size:15px;"
                 f"line-height:1.55;color:#3d3a35;margin-top:14px;padding-left:12px;"
                 f"border-left:2px solid {RULE}'>{escape(ai['portfolio'])}</div>")

    p.append(f"<div style='height:16px'></div>{TABLE}<tr>{th('Holding', 'left')}{th('Day')}"
             f"{th('Day $')}{th('Weight')}{th('Total')}</tr>")
    for r in port["rows"]:
        bar = (f"<span style='display:inline-block;width:{max(r['weight'] * 1.2, 2):.0f}px;"
               f"height:5px;background:#c7d0dc;border-radius:2px;vertical-align:middle;"
               f"margin-right:6px'></span>"
               + (f"{r['weight']:.0f}%" if r["weight"] >= 1 else "&lt;1%"))
        if r["cash"]:
            p.append(f"<tr>{td('Cash', 'left', f'color:{MUTED}')}{td('')}{td('')}"
                     f"{td(bar)}{td('')}</tr>")
            continue
        tag = (f" <span style='font-size:9px;font-weight:700;letter-spacing:.8px;color:{ACCENT};"
               f"border:1px solid {ACCENT};border-radius:3px;padding:0 3px;"
               f"vertical-align:middle'>BIG MOVE</span>" if abs(r["z"]) >= UNUSUAL_Z else "")
        p.append(f"<tr>{td(f'<b>{r['ticker']}</b>{tag}', 'left')}{td(signed(r['day']))}"
                 f"{td(signed_money(r['day_usd']))}{td(bar)}"
                 f"{td(signed(r['since_bought'], '{:+.1f}%'))}</tr>")
    p.append("</table>")
    if port["missing"]:
        p.append(f"<div style='font-family:{SANS};font-size:12px;color:{DOWN};margin-top:8px'>"
                 f"No price data today for {', '.join(port['missing'])}, so they are left out "
                 "of the totals.</div>")
    if holding_news:
        p.append(caption("Behind the moves"))
        p += [f"<div style='margin-bottom:8px'><span style='{NUM};font-size:12px;font-weight:700;"
              f"color:{MUTED}'>{t}</span>&nbsp; {link(*item)}</div>"
              for t, item in holding_news.items()]

    hist = port["history"]
    you = (hist.iloc[-1] / hist.iloc[0] - 1) * 100
    spx_hist = (spx["last"] / float(port["spx_start"]) - 1) * 100
    p.append(caption(f"Past 3 months &nbsp;<span style='color:{ACCENT}'>&#9632;</span> You "
                     f"{signed(you, '{:+.1f}%')} &nbsp;<span style='color:#bdb6a8'>&#9632;</span> "
                     f"S&amp;P 500 {signed(spx_hist, '{:+.1f}%')}"
                     + "".join(f" &nbsp;<span style='color:{SHADOW_COLOR}'>&#9632;</span> "
                               f"{escape(sh['name'])} "
                               + signed(_three_month(sh["history"], port["history"]), '{:+.1f}%')
                               for sh in (shadows or [])[:1])))
    p.append("<img src='cid:perf' width='100%' alt='Portfolio vs S&amp;P 500, past 3 months' "
             "style='display:block;width:100%;height:auto'>")

    if risk or exposure:
        p.append(risk_html(risk, exposure, corr, stress_tests))
    if valuation:
        p.append(deep_dive_html(valuation, ai and ai.get("deep_dive")))
    for sh in shadows or []:
        p.append(shadow_html(sh, risk, stress_tests))

    # World
    p.append(label("World at a Glance"))
    p.append(f"{TABLE}<tr>{th('', 'left')}{th('Level')}{th('Day')}{th('Year to date')}</tr>")
    for region, rows in world.items():
        if not rows:
            continue
        as_of = max(q["date"] for q in rows.values())
        p.append(f"<tr><td colspan='4' style='padding:14px 0 2px;font-family:{SERIF};"
                 f"font-size:15px;color:{INK}'>{region} <span style='font-family:{SANS};"
                 f"font-size:11px;color:{FAINT}'>&nbsp;close {as_of:%a %b} {as_of.day}</span></td></tr>")
        for name, q in rows.items():
            p.append(f"<tr>{td(name, 'left')}{td(f'{q['last']:,.0f}')}{td(signed(q['day']))}"
                     f"{td(signed(q['ytd'], '{:+.1f}%'))}</tr>")
    p.append("</table>")
    if futures:
        p.append(f"<div style='{NUM};font-size:12.5px;color:{MUTED};margin-top:10px'>"
                 f"US futures this morning: "
                 + DOT.join(f"{n} {signed(q['day'])}" for n, q in futures.items()) + "</div>")

    # What moved
    p.append(label("What Moved"))
    p.append(caption("US sectors today").replace("margin:18px 0 6px", "margin:0 0 6px"))
    p.append("<img src='cid:sectors' width='100%' alt='US sector moves today' "
             "style='display:block;width:100%;height:auto'>")
    if movers["up"] or movers["down"]:
        p.append(caption(f"Biggest moves among US companies worth "
                         f"${MOVER_MIN_CAP / 1e9:.0f}B+"))
        for m in movers["up"] + movers["down"]:
            head = mover_news.get(m["ticker"])
            p.append(f"<div style='padding:10px 0;border-bottom:1px solid {HAIR}'>{TABLE}<tr>"
                     f"<td style='font-family:{SANS};font-size:13.5px;color:{INK}'>"
                     f"<b>{m['ticker']}</b>&nbsp; <span style='color:{MUTED}'>{escape(m['name'])}"
                     f"</span></td><td style='text-align:right'>"
                     f"{chip(f'{m['day']:+.1f}%', m['day'])}</td></tr></table>"
                     + (f"<div style='margin-top:4px'>{link(*head, size=14)}</div>" if head else "")
                     + "</div>")

    # Rates, FX, commodities
    p.append(label("Rates, FX &amp; Commodities"))
    p.append(TABLE)
    for name, q in macro.items():
        if "bps" in q:
            level, change = f"{q['last']:.2f}%", signed(q["bps"], "{:+.0f} bps")
        else:
            level = f"{q['last']:,.{4 if q['last'] < 10 else 2}f}"
            change = signed(q["day"])
        p.append(f"<tr>{td(name, 'left')}{td(level)}{td(change)}</tr>")
    p.append("</table>")

    # What to watch
    if (ai and ai["watch"]) or events:
        p.append(label("What to Watch"))
        if ai:
            p += [f"<div style='font-family:{SERIF};font-size:15.5px;line-height:1.55;"
                  f"color:{INK};padding-left:12px;border-left:2px solid {ACCENT};"
                  f"margin-bottom:10px'>{escape(w)}</div>" for w in ai["watch"]]
        if events:
            p.append(f"<div style='height:6px'></div>{TABLE}")
            p += [f"<tr>{td(f'{d:%a %b} {d.day}', 'left', f'width:92px;color:{MUTED};font-size:12.5px')}"
                  f"{td(escape(e), 'left')}</tr>" for d, e in events]
            p.append("</table>")

    # Headlines
    for name, items in news.items():
        if items:
            p.append(label("Headlines" if name == "Markets" else f"{name} Headlines"))
            for title, url in items:
                head, _, source = title.rpartition(" - ")
                p.append(f"<div style='margin-bottom:10px'>{link(head or title, url)}"
                         + (f"<span style='font-family:{SANS};font-size:11.5px;color:{FAINT}'>"
                            f"&nbsp; {escape(source)}</span>" if head else "") + "</div>")

    p.append(f"<div style='border-top:1px solid {RULE};margin-top:30px;padding-top:14px;"
             f"font-family:{SANS};font-size:11px;line-height:1.6;color:{FAINT}'>"
             "Day changes are vs. the prior close; Total is the gain since you bought. Data from Yahoo Finance and Google News, may be "
             "delayed. The 3-month chart and risk stats use today's holdings as if held over "
             "the period (risk: past year of daily returns; bad day is the 5th-worst percentile "
             "day; fund look-through uses each fund's top 10 holdings). "
             "The Take, portfolio note and watch list are written by Claude from this data "
             "only. Not investment advice.</div>")

    body = "".join(p)
    return (f"<div style='background:{PAPER};padding:24px 10px'>"
            f"<table role='presentation' align='center' width='100%' cellpadding='0' "
            f"cellspacing='0' style='max-width:620px;background:{CARD};border:1px solid {RULE}'>"
            f"<tr><td style='padding:30px 26px 26px'>{body}</td></tr></table></div>")


def build_text(port, ai):
    lines = ["The Daily Letter", f"{datetime.now(ET):%A, %B %d, %Y}", ""]
    if ai:
        lines += [ai["take"], ""]
    lines.append(f"Portfolio: ${port['value']:,.2f}, {money(port['day_usd'])} "
                 f"({port['day']:+.2f}%) today")
    lines += [f"  {r['ticker']}: {r['day']:+.2f}%" for r in port["rows"] if not r["cash"]]
    return "\n".join(lines)


def send(subject, html, text, images):
    sender = os.environ["GMAIL_ADDRESS"]
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = os.environ.get("TO_ADDRESS", sender)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)
    for cid, png in images.items():
        img = MIMEImage(png, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)


def main():
    holdings = load_portfolio()
    movers = screen_movers()
    world_tickers = [t for rows in WORLD.values() for t in rows.values()]
    data = download([h["ticker"] for h in holdings if h["ticker"] not in CASH]
                    + world_tickers + list(FUTURES.values()) + list(MACRO.values())
                    + list(SECTORS.values()) + [RISK_FREE] + list(regime.TICKERS.values())
                    + shadow.tickers())

    def pick(names):
        return {n: stats(data[t], t) for n, t in names.items() if t in data}

    world = {region: pick(rows) for region, rows in WORLD.items()}
    futures, macro, sectors = pick(FUTURES), pick(MACRO), pick(SECTORS)
    port = portfolio_view(holdings, data)
    port["spx_start"] = data["^GSPC"].reindex(port["history"].index).ffill().iloc[0]

    mover_news = {m["ticker"]: h for m in movers["up"] + movers["down"]
                  if (h := ticker_headline(m["ticker"], m["name"]))}
    # Explain only the holdings that really moved, biggest first
    standouts = sorted((r for r in port["rows"] if not r["cash"] and
                        (abs(r["z"]) >= UNUSUAL_Z or abs(r["day"]) >= HOLDING_NEWS_MOVE)),
                       key=lambda r: abs(r["day_usd"]), reverse=True)[:3]
    holding_news = {r["ticker"]: h for r in standouts if (h := ticker_headline(r["ticker"]))}
    news = market_headlines()
    events = calendar(holdings)

    # Analytics never block the letter: if one fails, its section is just left out
    rf = float(data[RISK_FREE].iloc[-1]) / 100 if RISK_FREE in data else 0.0
    risk_stats = exposure = corr = None
    try:
        risk_stats = risk.risk_view(port["history_1y"], data["^GSPC"], rf)
    except Exception as e:
        print("Risk stats skipped:", e)
    try:
        exposure = risk.exposure_view(port["rows"])
    except Exception as e:
        print("Exposure skipped:", e)
    try:
        corr = risk.correlations(port["prices"])
    except Exception as e:
        print("Correlations skipped:", e)
    weather = stress_tests = None
    try:
        weather = regime.regime(data)
    except Exception as e:
        print("Market regime skipped:", e)
    try:
        stress_tests = {"replays": stress.replays(port["rows"]),
                        "shocks": stress.shocks(port["rows"], data),
                        "ai": stress.ai_exposure(exposure)}
    except Exception as e:
        print("Stress tests skipped:", e)
    try:
        shadows = shadow.evaluate(port, data, data["^GSPC"], rf)
    except Exception as e:
        print("Shadow portfolios skipped:", e)
        shadows = []

    valuation = None
    if "US 10Y yield" in macro:
        try:
            valuation = deep_dive(holdings, macro["US 10Y yield"]["last"] / 100)
        except Exception as e:
            print("Deep dive skipped:", e)

    day = str(world["US"]["S&P 500"]["date"])  # the US session this letter covers
    brief = build_brief(port, world, futures, macro, sectors, movers, mover_news,
                        holding_news, news, events, risk_stats, exposure, corr,
                        history.recent_letters(day), history.recent_portfolio(day), valuation,
                        weather, stress_tests, shadows)
    ai = ai_take(brief)
    html = build_html(port, world, futures, macro, movers, mover_news, holding_news,
                      news, events, ai, risk_stats, exposure, corr, valuation,
                      weather, stress_tests, shadows)
    text = build_text(port, ai)
    images = {"perf": perf_chart(port, data["^GSPC"], shadows), "sectors": sector_chart(sectors)}
    subject = (f"Daily Letter | {datetime.now(ET):%b %d} | Portfolio {port['day']:+.2f}%, "
               f"S&P {world['US']['S&P 500']['day']:+.2f}%")

    if os.environ.get("DRY_RUN"):
        for cid, png in images.items():
            html = html.replace(f"cid:{cid}", f"{cid}.png")
            with open(os.path.join(HERE, f"{cid}.png"), "wb") as f:
                f.write(png)
        with open(os.path.join(HERE, "preview.html"), "w", encoding="utf-8") as f:
            f.write(f"<meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    f"<title>{escape(subject)}</title><body style='margin:0'>{html}</body>")
        with open(os.path.join(HERE, "brief.txt"), "w", encoding="utf-8") as f:
            f.write(brief)
        print("Preview written:", subject)
    else:
        send(subject, html, text, images)
        print("Sent:", subject)
        history.save_day(day, port, {"World": {f"{r} {n}": q for r, rows in world.items()
                                               for n, q in rows.items()},
                                     "Futures": futures, "Macro": macro, "Sectors": sectors},
                         ai, movers, risk_stats, {
                             "regime": weather and weather["name"],
                             "regime_score": weather and weather["score"],
                             "ai_exposure_pct": (stress_tests and stress_tests["ai"]
                                                 and round(stress_tests["ai"]["pct"], 2))})
        if valuation:
            history.save_valuation(day, valuation)
        history.save_shadows(day, shadows)
        print("Saved history for", day)


if __name__ == "__main__":
    main()
