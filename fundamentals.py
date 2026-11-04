"""Company fundamentals for the DCF Lab: several years of the line items an unlevered
free cash flow model is built from, archived to data/fundamentals/<TICKER>.json.

Each run merges the latest statements into the archive by fiscal year, so a company's
history keeps growing even though Yahoo only serves the last four years.

Free cash flow to the firm (FCFF) = EBIT x (1 - tax rate) + D&A - capex - increase in NWC
"""
import json
import os
from datetime import datetime

import yfinance as yf

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fundamentals")
LINES = {  # field: (statement, Yahoo row names tried in order)
    "revenue": ("income", ["Total Revenue"]),
    "ebit": ("income", ["Operating Income", "EBIT"]),
    "da": ("cash", ["Depreciation And Amortization", "Reconciled Depreciation"]),
    "interest": ("income", ["Interest Expense"]),
    "tax_rate": ("income", ["Tax Rate For Calcs"]),
    "net_income": ("income", ["Net Income"]),
    "ocf": ("cash", ["Operating Cash Flow"]),
    "capex": ("cash", ["Capital Expenditure"]),
    "wc_change": ("cash", ["Change In Working Capital"]),
    "fcf": ("cash", ["Free Cash Flow"]),
    "buybacks": ("cash", ["Repurchase Of Capital Stock"]),
    "dividends": ("cash", ["Cash Dividends Paid"]),
    "debt": ("balance", ["Total Debt"]),
    "cash": ("balance", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]),
    "equity": ("balance", ["Stockholders Equity"]),
    "shares": ("balance", ["Ordinary Shares Number"]),
}


def _num(v):
    return None if v is None or v != v else float(v)


def fetch(ticker):
    """Latest statements and market data from Yahoo, newest fiscal year last."""
    t = yf.Ticker(ticker)
    frames = {"income": t.income_stmt, "cash": t.cashflow, "balance": t.balance_sheet}
    years = {}
    for col in frames["income"].columns:
        fy = str(col.year)
        row = {"fy": fy, "period_end": str(col.date())}
        for field, (stmt, names) in LINES.items():
            df = frames[stmt]
            name = next((n for n in names if n in df.index), None)
            row[field] = _num(df.loc[name, col]) if name and col in df.columns else None
        # Store outflows as positive numbers, as an analyst would write them in a model
        for field in ("capex", "buybacks", "dividends"):
            if row[field] is not None:
                row[field] = abs(row[field])
        # Cash flow statements show a working-capital *source* as positive; the model wants
        # the investment in working capital, so flip the sign
        wc = row.pop("wc_change")
        row["nwc_investment"] = -wc if wc is not None else None
        if row["revenue"]:
            years[fy] = row
    info = t.info
    growth = {}
    try:
        re = t.revenue_estimate
        growth = {p: _num(re.loc[p, "growth"]) for p in ("0y", "+1y") if p in re.index}
    except Exception:
        pass
    return {
        "ticker": ticker, "name": info.get("shortName") or ticker, "sector": info.get("sector"),
        "industry": info.get("industry"), "currency": info.get("financialCurrency") or "USD",
        "price": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
        "shares_out": _num(info.get("sharesOutstanding")), "beta": _num(info.get("beta")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "analyst_growth": [growth.get("0y"), growth.get("+1y")],
        "years": years, "fetched": datetime.now().strftime("%Y-%m-%d"),
    }


def update(ticker):
    """Fetch the latest and merge it into the archive. Returns the merged record."""
    path = os.path.join(DIR, f"{ticker}.json")
    record = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    try:
        latest = fetch(ticker)
    except Exception as e:
        print(f"Fundamentals for {ticker} not refreshed:", e)
        return record or None
    if not latest["years"]:  # funds and anything without financial statements
        return record or None
    years = {**record.get("years", {}), **latest["years"]}  # newer filings win
    record = {**latest, "years": dict(sorted(years.items()))}
    os.makedirs(DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    return record
