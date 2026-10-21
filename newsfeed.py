"""Company headlines from Yahoo Finance, with a fallback.

Yahoo's per-ticker news feed sometimes returns nothing for days at a time, so when it does,
fall back to Yahoo's search endpoint and keep the articles tagged with that ticker.
"""
from datetime import datetime, timedelta, timezone

import yfinance as yf


def _from_feed(ticker):
    out = []
    for item in yf.Ticker(ticker).news or []:
        c = item.get("content") or {}
        if not c.get("title") or not c.get("pubDate"):
            continue
        link = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url", "")
        out.append((c["title"], link,
                    datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))))
    return out


def _from_search(ticker):
    out = []
    for item in yf.Search(ticker, news_count=12).news or []:
        related = item.get("relatedTickers") or []
        if related and ticker not in related:
            continue
        out.append((item["title"], item.get("link", ""),
                    datetime.fromtimestamp(item["providerPublishTime"], timezone.utc)))
    return out


def ticker_news(ticker, max_age=timedelta(days=2)):
    """[(title, link, published datetime)] for `ticker`, newest first, within `max_age`."""
    items = []
    for source in (_from_feed, _from_search):
        try:
            items = source(ticker)
        except Exception:
            items = []
        if items:
            break
    cutoff = datetime.now(timezone.utc) - max_age
    return sorted((i for i in items if i[2] >= cutoff), key=lambda i: i[2], reverse=True)
