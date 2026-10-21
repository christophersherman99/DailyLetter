"""Economic calendar from official sources.

- Fed meetings: federalreserve.gov's FOMC calendar (decision on the meeting's last day)
- GDP, PCE inflation and spending, trade: the Bureau of Economic Analysis release schedule
- CPI, jobs, producer prices, retail sales: the St. Louis Fed's FRED API, only if a free
  FRED_API_KEY is set (the Bureau of Labor Statistics blocks automated requests)

Each event carries a one-line note on why markets care.
"""
import os
import re
from datetime import date, timedelta

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (DailyLetter; personal market newsletter)"}
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
WHY = {
    "fomc": "The Fed sets short-term rates; surprises move bonds, the dollar, and growth stocks",
    "gdp": "The broadest read on growth; a big miss shifts recession odds and rate expectations",
    "pce": "The Fed's preferred inflation gauge, plus consumer spending",
    "trade": "Exports minus imports; feeds into GDP and tariff debates",
    "cpi": "Consumer inflation; a hot reading tends to lift yields and weigh on growth stocks",
    "jobs": "Payrolls and unemployment; the clearest monthly read on the economy",
    "ppi": "Producer prices, an early hint of where consumer inflation is heading",
    "retail": "Retail sales show how hard consumers are spending",
}
FRED_RELEASES = {10: ("CPI inflation report", "cpi"), 50: ("Jobs report", "jobs"),
                 46: ("Producer prices (PPI)", "ppi"), 9: ("Retail sales", "retail")}


def _get(url, **params):
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r


def fomc(today):
    """Fed rate decisions: the last day of each scheduled meeting."""
    html = _get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm").text
    out = []
    for year, panel in re.findall(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", html, re.S):
        for month, days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?'
                                      r'fomc-meeting__date[^>]*>([^<]+)<', panel, re.S):
            last_month = month.split("/")[-1].strip()
            last_day = re.findall(r"\d+", days)[-1] if re.findall(r"\d+", days) else None
            if last_month not in MONTHS or not last_day:
                continue
            d = date(int(year), MONTHS[last_month], int(last_day))
            out.append((d, "Fed rate decision (FOMC)", WHY["fomc"]))
    return [e for e in out if e[0] >= today]


def bea(today):
    """GDP, PCE inflation and spending, and the trade balance."""
    html = _get("https://www.bea.gov/news/schedule").text
    out = []
    for when, title in re.findall(r'scheduled-releases-type-press.*?release-date">([^<]+)</div>.*?'
                                  r'release-title[^>]*>([^<]+)</td>', html, re.S):
        month, _, day = when.strip().partition(" ")
        if month not in MONTHS or not day.strip().isdigit():
            continue
        d = date(today.year, MONTHS[month], int(day))
        if d < today - timedelta(days=60):  # the schedule rolls into next year
            d = d.replace(year=today.year + 1)
        title = " ".join(title.split())
        period = title.rsplit(",", 1)[-1].strip()
        if title.startswith("GDP") and "Quarter" in title:  # quarterly GDP, not annual reports
            stage = re.search(r"\((.*?)\)", title)
            out.append((d, f"GDP, {period}" + (f" ({stage.group(1).lower()})" if stage else ""), WHY["gdp"]))
        elif title.startswith("Personal Income and Outlays"):
            out.append((d, f"PCE inflation and spending, {period}", WHY["pce"]))
        elif title.startswith("U.S. International Trade in Goods and Services"):
            out.append((d, f"Trade balance, {period}", WHY["trade"]))
    return [e for e in out if e[0] >= today]


def fred(today, key):
    out = []
    for release_id, (name, why) in FRED_RELEASES.items():
        r = _get("https://api.stlouisfed.org/fred/release/dates", release_id=release_id,
                 api_key=key, file_type="json", realtime_start=str(today),
                 include_release_dates_with_no_data="true", sort_order="asc", limit=3).json()
        out += [(date.fromisoformat(x["date"]), name, WHY[why]) for x in r.get("release_dates", [])]
    return [e for e in out if e[0] >= today]


def calendar(today, horizon_days=30):
    """[(date, event, why it matters)] within the horizon, from every source that responds."""
    events = []
    sources = [fomc, bea]
    key = os.environ.get("FRED_API_KEY")
    for source in sources + ([lambda t: fred(t, key)] if key else []):
        try:
            events += source(today)
        except Exception as e:
            print("Economic calendar source failed:", getattr(source, "__name__", "fred"), e)
    end = today + timedelta(days=horizon_days)
    return sorted({e for e in events if e[0] <= end})
