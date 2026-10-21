"""Catalyst radar: event-driven news for holdings, a personal watchlist, mid-size companies
making outsized moves, and market-wide FDA and deal headlines.

Headlines are tagged by type with keyword rules (first match wins), and unusual trading
volume is flagged even without news, since volume often moves before headlines do.
"""
import csv
import os
import re
from datetime import timedelta

import feedparser
import yfinance as yf

from newsfeed import ticker_news

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(HERE, "watchlist.csv")

# (type, pattern). Order matters: the first matching rule tags the headline.
RULES = [
    ("FDA", r"\bFDA\b|\bEMA\b|PDUFA|breakthrough (therapy|device)|complete response letter|"
            r"\bapprov\w*\b.{0,40}\b(drug|therap\w*|device|treatment|test|vaccine)\b"),
    ("Trial", r"\bphase (1|2|3|i{1,3})\b|trial (results|data)|topline|primary endpoint"),
    ("Deal", r"\bacqui(re|res|red|ring|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|"
             r"\bto buy\b|\bbid for\b|tender offer|\bspin[- ]?off\b"),
    # A company changing its own forecast ("raises outlook"), not analysts reacting to one
    ("Guidance", r"\b(raises|raised|lifts|lifted|cuts|lowers|lowered|boosts|boosted|slashes|"
                 r"slashed|reaffirms|reiterates|withdraws|pulls)\b.{0,25}\b(guidance|outlook|"
                 r"forecast)\b|\bguidance\b"),
    # Results and previews, not valuation talk like "24 times forward earnings"
    ("Earnings", r"\b(earnings|results)\b.{0,3}\b(beats?|miss(es)?|report\w*|preview|call|date|"
                 r"to watch|setup|season)\b|\b(q[1-4]|quarterly|(first|second|third|fourth)[- ]"
                 r"quarter)\b.{0,20}\b(results|earnings|revenue|profit|sales|loss)\b|"
                 r"\b(beats|misses|tops)\b.{0,20}\b(estimates|expectations|forecasts)\b"),
    ("Leadership", r"\bCEO\b.{0,40}\b(steps? down|resign\w*|depart\w*|appoint\w*|named|retir\w*|"
                   r"oust\w*)\b|\b(steps? down|resigns?)\b"),
    ("Legal", r"\blawsuit\b|\bantitrust\b|\bSEC\b|\bDOJ\b|\bprobe\b|\binvestigation\b|"
              r"\bsettle\w*\b|\bsubpoena\b"),
    ("Capital", r"\bbuyback\b|\brepurchase\b|dividend (increase|hike|raise|cut)|stock split|"
                r"\boffering\b|\bconvertible\b"),
]
_RULES = [(t, re.compile(p, re.I)) for t, p in RULES]
MARKET_FEEDS = {
    "FDA": "https://news.google.com/rss/search?q=FDA+approves+when:1d&hl=en-US&gl=US&ceid=US:en",
    "Deal": "https://news.google.com/rss/search?q=%22agrees+to+acquire%22+OR+%22to+acquire%22+"
            "billion+when:1d&hl=en-US&gl=US&ceid=US:en",
}
MIDCAP = (2e9, 10e9)      # complements the $10B+ movers list in the letter
MIDCAP_MOVE = 8           # percent
VOLUME_SPIKE = 2.0        # today's volume vs its 20-day average
MAX_AGE = timedelta(days=2)


def classify(title):
    for kind, rx in _RULES:
        if rx.search(title):
            return kind
    return None


def load_watchlist():
    if not os.path.exists(WATCHLIST):
        return {}
    with open(WATCHLIST, newline="", encoding="utf-8-sig") as f:
        return {r["ticker"].strip().upper(): (r.get("note") or "").strip()
                for r in csv.DictReader(f) if r.get("ticker")}


def headlines(ticker, max_age=MAX_AGE, with_dates=False):
    """Recent headlines for a ticker: [(title, link)], newest first."""
    return [(t, link, p.date()) if with_dates else (t, link)
            for t, link, p in ticker_news(ticker, max_age)]


def _words(title):
    return {w for w in re.findall(r"[a-z0-9$]+", title.lower().rsplit(" - ", 1)[0]) if len(w) > 3}


def _dedupe(items, key="title", overlap=0.5):
    """Drop headlines that mostly repeat an earlier one (same story, different outlet)."""
    kept = []
    for it in items:
        w = _words(it[key])
        if all(len(w & _words(k[key])) / max(1, min(len(w), len(_words(k[key])))) < overlap
               for k in kept):
            kept.append(it)
    return kept


def _about(title, ticker, name):
    """Does the headline name the company (ticker or first word of its name)?"""
    keys = {ticker.lower(), *re.findall(r"[a-z0-9]+", name.lower())[:1]}
    words = set(re.findall(r"[a-z0-9]+", title.lower()))
    return bool(keys & words)


def relevant(ticker, name="", max_age=MAX_AGE, with_dates=False):
    """Headlines that actually name the company."""
    return [h for h in headlines(ticker, max_age, with_dates) if _about(h[0], ticker, name)]


def tagged(ticker, limit=2, name=""):
    """Up to `limit` catalyst headlines for a ticker, one per type."""
    seen, out = set(), []
    for title, link in relevant(ticker, name):
        kind = classify(title)
        if kind and kind not in seen:
            seen.add(kind)
            out.append({"type": kind, "title": title, "link": link})
            if len(out) == limit:
                break
    return out


def volume_ratios(tickers):
    """{ticker: today's volume / prior 20-day average volume}."""
    if not tickers:
        return {}
    try:
        df = yf.download(sorted(tickers), period="3mo", auto_adjust=True, group_by="ticker",
                         progress=False, threads=True)
    except Exception:
        return {}
    out = {}
    for t in tickers:
        try:
            v = df[t]["Volume"].dropna()
            v = v[v > 0]
            if len(v) > 21:
                out[t] = float(v.iloc[-1]) / float(v.iloc[-21:-1].mean())
        except KeyError:
            continue
    return out


def midcap_jumpers(n=5):
    """$2-10B US companies that moved 8%+ in the latest session."""
    Q = yf.EquityQuery
    out = []
    for op, threshold, asc in (("gt", MIDCAP_MOVE, False), ("lt", -MIDCAP_MOVE, True)):
        try:
            query = Q("and", [Q("eq", ["region", "us"]),
                              Q("is-in", ["exchange", "NYQ", "NMS", "NGM", "NCM", "ASE"]),
                              Q("btwn", ["intradaymarketcap", *MIDCAP]),
                              Q(op, ["percentchange", threshold])])
            res = yf.screen(query, sortField="percentchange", sortAsc=asc, size=n)
            out += [{"ticker": r["symbol"], "name": r.get("shortName") or r["symbol"],
                     "day": r["regularMarketChangePercent"]} for r in res.get("quotes", [])]
        except Exception as e:
            print("Mid-cap screen failed:", e)
    return out


def market_wide(n=2):
    out = []
    for kind, url in MARKET_FEEDS.items():
        try:
            entries = [{"type": kind, "title": e.title, "link": e.link}
                       for e in feedparser.parse(url).entries[:12]]
            out += _dedupe(entries)[:n]
        except Exception:
            pass
    return out


def scan(holdings, moves, names=None):
    """Run the radar.

    holdings: tickers held (cash excluded); moves: {ticker: day % move} for known tickers;
    names: {ticker: company name}. Returns watchlist rows, catalyst items, market headlines.
    """
    names = dict(names or {})
    watch = load_watchlist()
    volumes = volume_ratios(set(holdings) | set(watch))

    watchlist = []
    for t, note in watch.items():
        # Watchlist names are followed closely: show the latest headline from the past week
        heads = relevant(t, note, timedelta(days=7), with_dates=True)
        top = next((h for h in heads if classify(h[0])), heads[0] if heads else None)
        watchlist.append({"ticker": t, "note": note, "day": moves.get(t),
                          "volume": volumes.get(t), "type": top and classify(top[0]),
                          "title": top and top[0], "link": top and top[1],
                          "date": top and str(top[2])})

    items = []
    for t in holdings:
        for h in tagged(t, name=names.get(t, "")):
            items.append({"ticker": t, "name": names.get(t, t), "source": "holding",
                          "day": moves.get(t), **h})
        ratio = volumes.get(t)
        if ratio and ratio >= VOLUME_SPIKE and not any(i["ticker"] == t for i in items):
            items.append({"ticker": t, "name": names.get(t, t), "source": "holding",
                          "day": moves.get(t), "type": "Volume",
                          "title": f"Trading at {ratio:.1f}x its usual volume, no headline yet",
                          "link": ""})
    for m in midcap_jumpers():
        names.setdefault(m["ticker"], m["name"])
        found = tagged(m["ticker"], 1, m["name"])
        if not found:  # no catalyst keyword: still show the latest headline as context
            heads = relevant(m["ticker"], m["name"])
            found = [{"type": None, "title": heads[0][0], "link": heads[0][1]}] if heads else []
        items.append({"ticker": m["ticker"], "name": m["name"], "source": "mover", "day": m["day"],
                      **(found[0] if found else {"type": None, "title": None, "link": ""})})
    return {"watchlist": watchlist, "items": items, "market": market_wide()}
