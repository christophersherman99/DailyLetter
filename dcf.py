"""Discounted cash flow (DCF) valuation from public financial data.

Method (two-stage, unlevered free cash flow):
  1. Revenue is projected 10 years ahead. Years 1-2 use analyst revenue growth estimates when
     available (historical growth otherwise); growth then fades in a straight line to the
     terminal growth rate by year 10.
  2. Free cash flow = projected revenue x the company's median free cash flow margin over
     its last 3 reported years.
  3. Cash flows are discounted at the weighted average cost of capital (WACC). Cost of
     equity comes from CAPM (risk-free rate + beta x equity risk premium); cost of debt from
     interest expense / total debt, after tax. Weights use market values.
  4. Terminal value uses the Gordon growth model at the end of year 10.
  5. Equity value = enterprise value - debt + cash, divided by shares outstanding.
Also produces a WACC x terminal growth sensitivity grid and a reverse DCF: the constant
10-year revenue growth rate that would justify today's share price.

Banks and insurers are skipped: debt is their raw material rather than financing, so a
free-cash-flow DCF does not describe them. They are usually valued on book value or
dividends instead.

Run on its own:  python dcf.py AAPL MSFT
"""
import math
import statistics
import sys

import yfinance as yf

EQUITY_RISK_PREMIUM = 0.05
TERMINAL_GROWTH = 0.025
YEARS = 10
DEFAULT_TAX = 0.21
SKIP_SECTORS = {"Financial Services"}
GROWTH_BOUNDS = (-0.15, 0.40)


def _row(df, *names):
    """The first matching row of a financial statement, oldest year last, NaNs dropped."""
    for name in names:
        if name in df.index:
            return [float(v) for v in df.loc[name].tolist() if v == v]
    return []


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def gather(ticker, rf):
    """Collect model inputs for `ticker`. Returns (inputs, None) or (None, reason skipped)."""
    t = yf.Ticker(ticker)
    info = t.info
    if info.get("quoteType") != "EQUITY":
        return None, "not an operating company"
    if info.get("sector") in SKIP_SECTORS:
        return None, "banks and insurers are not valued with a cash flow DCF"
    cf, inc, bs = t.cashflow, t.income_stmt, t.balance_sheet

    revenue = _row(inc, "Total Revenue")
    fcf = _row(cf, "Free Cash Flow")
    if len(revenue) < 2 or not fcf:
        return None, "not enough reported financials"
    margins = [f / r for f, r in zip(fcf[:3], revenue[:3]) if r]
    fcf_margin = statistics.median(margins)
    if fcf_margin <= 0:
        return None, "free cash flow is negative, so a DCF is not meaningful"

    # Growth for years 1-2: analyst revenue estimates, else historical annual growth
    hist_growth = (revenue[0] / revenue[-1]) ** (1 / (len(revenue) - 1)) - 1
    est = {}
    try:
        re = t.revenue_estimate
        est = {p: float(re.loc[p, "growth"]) for p in ("0y", "+1y")
               if p in re.index and re.loc[p, "growth"] == re.loc[p, "growth"]}
    except Exception:
        pass
    g1 = est.get("0y", hist_growth)
    g2 = est.get("+1y", g1)
    g1, g2 = (_clip(g, *GROWTH_BOUNDS) for g in (g1, g2))

    taxes = _row(inc, "Tax Rate For Calcs")
    tax = _clip(statistics.median(taxes[:3]), 0, 0.35) if taxes else DEFAULT_TAX
    debt = (_row(bs, "Total Debt") or [0.0])[0]
    cash = (_row(bs, "Cash Cash Equivalents And Short Term Investments",
                 "Cash And Cash Equivalents") or [0.0])[0]
    interest = next((abs(v) for v in _row(inc, "Interest Expense") if v), 0.0)
    cost_of_debt = _clip(interest / debt, rf, rf + 0.06) if debt and interest else rf + 0.015

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    if not price or not shares:
        return None, "missing price or share count"
    return {
        "ticker": ticker, "name": info.get("shortName") or ticker,
        "sector": info.get("sector", ""), "price": float(price), "shares": float(shares),
        "revenue": revenue[0], "fiscal_year": str(inc.columns[0].year),
        "fcf_margin": fcf_margin, "growth": [g1, g2], "growth_source":
            "analyst estimates" if est else "historical growth",
        "hist_growth": hist_growth, "beta": _clip(float(info.get("beta") or 1.0), 0.4, 2.5),
        "rf": rf, "tax": tax, "debt": debt, "cash": cash, "cost_of_debt": cost_of_debt,
    }, None


def wacc(inp):
    equity = inp["price"] * inp["shares"]
    total = equity + inp["debt"]
    cost_of_equity = inp["rf"] + inp["beta"] * EQUITY_RISK_PREMIUM
    after_tax_debt = inp["cost_of_debt"] * (1 - inp["tax"])
    return {"wacc": (equity * cost_of_equity + inp["debt"] * after_tax_debt) / total,
            "cost_of_equity": cost_of_equity, "after_tax_debt": after_tax_debt,
            "equity_weight": equity / total}


def growth_path(g1, g2, terminal):
    """Years 1-2 as given, then a straight-line fade to terminal growth by the final year."""
    steps = YEARS - 2
    return [g1, g2] + [g2 + (terminal - g2) * k / steps for k in range(1, steps + 1)]


def value(inp, rate, terminal, growth=None):
    """Per-share value at discount rate `rate` and terminal growth `terminal`."""
    if rate <= terminal:
        return None
    growth = growth or growth_path(*inp["growth"], terminal)
    revenue, rows, pv_sum = inp["revenue"], [], 0.0
    for year, g in enumerate(growth, start=1):
        revenue *= 1 + g
        fcf = revenue * inp["fcf_margin"]
        pv = fcf / (1 + rate) ** year
        pv_sum += pv
        rows.append({"year": year, "growth": g, "revenue": revenue, "fcf": fcf, "pv": pv})
    terminal_value = rows[-1]["fcf"] * (1 + terminal) / (rate - terminal)
    pv_terminal = terminal_value / (1 + rate) ** YEARS
    ev = pv_sum + pv_terminal
    equity = ev - inp["debt"] + inp["cash"]
    return {"per_share": equity / inp["shares"], "ev": ev, "equity": equity,
            "pv_terminal": pv_terminal, "terminal_share": pv_terminal / ev, "rows": rows}


def implied_growth(inp, rate, terminal):
    """Reverse DCF: constant 10-year revenue growth that makes value equal today's price."""
    lo, hi = -0.30, 0.80
    f = lambda g: value(inp, rate, terminal, [g] * YEARS)["per_share"] - inp["price"]
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def run(ticker, rf):
    """Full valuation for one ticker, or {'ticker', 'skipped'} with the reason."""
    inp, reason = gather(ticker, rf)
    if not inp:
        return {"ticker": ticker, "skipped": reason}
    w = wacc(inp)
    base = value(inp, w["wacc"], TERMINAL_GROWTH)
    rates = [w["wacc"] + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    terminals = [TERMINAL_GROWTH + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    grid = [[(v := value(inp, r, g)) and v["per_share"] for g in terminals] for r in rates]
    return {**inp, **w, **base, "terminal_growth": TERMINAL_GROWTH,
            "upside": base["per_share"] / inp["price"] - 1,
            "implied_growth": implied_growth(inp, w["wacc"], TERMINAL_GROWTH),
            "grid": grid, "grid_rates": rates, "grid_terminals": terminals}


def report(v):
    """Plain-text model for the command line."""
    if v.get("skipped"):
        return f"{v['ticker']}: skipped ({v['skipped']})"
    b = lambda x: f"${x / 1e9:,.1f}B"
    gap = v["price"] / v["per_share"] - 1
    L = [f"{v['name']} ({v['ticker']})  price ${v['price']:,.2f}  fair value "
         f"${v['per_share']:,.2f}  ({v['upside']:+.0%})",
         f"The model value is {abs(v['upside']):.0%} {'below' if v['upside'] < 0 else 'above'} "
         f"the price; the price is {abs(gap):.0%} {'above' if gap > 0 else 'below'} the model "
         "value.", "",
         f"Revenue FY{v['fiscal_year']}: {b(v['revenue'])}   FCF margin: {v['fcf_margin']:.1%}   "
         f"growth yrs 1-2: {v['growth'][0]:.1%}, {v['growth'][1]:.1%} ({v['growth_source']})",
         f"WACC {v['wacc']:.2%} = {v['equity_weight']:.0%} equity at {v['cost_of_equity']:.2%} "
         f"(rf {v['rf']:.2%} + beta {v['beta']:.2f} x ERP {EQUITY_RISK_PREMIUM:.0%}) + "
         f"{1 - v['equity_weight']:.0%} debt at {v['after_tax_debt']:.2%} after tax",
         "", f"{'Year':>4} {'Growth':>8} {'Revenue':>10} {'FCF':>10} {'PV of FCF':>10}"]
    L += [f"{r['year']:>4} {r['growth']:>8.1%} {b(r['revenue']):>10} {b(r['fcf']):>10} "
          f"{b(r['pv']):>10}" for r in v["rows"]]
    L += ["", f"Enterprise value {b(v['ev'])} (terminal value {v['terminal_share']:.0%} of it)"
          f" - debt {b(v['debt'])} + cash {b(v['cash'])} = equity {b(v['equity'])}"]
    ig = v["implied_growth"]
    L += [f"Reverse DCF: today's price implies {ig:.1%} revenue growth a year for {YEARS} years"
          if ig is not None else "Reverse DCF: no growth rate in range justifies the price"]
    L += ["", "Sensitivity, value per share (rows WACC, columns terminal growth):",
          "        " + "".join(f"{g:>9.1%}" for g in v["grid_terminals"])]
    L += [f"{r:>7.1%} " + "".join(f"{c:>9,.0f}" if c else f"{'n/a':>9}" for c in row)
          for r, row in zip(v["grid_rates"], v["grid"])]
    return "\n".join(L)


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL"]
    tnx = yf.Ticker("^TNX").history(period="5d")["Close"].dropna()
    rf = float(tnx.iloc[-1]) / (1000 if tnx.iloc[-1] > 20 else 100)
    for tk in tickers:
        print(report(run(tk.upper(), rf)), end="\n\n")
