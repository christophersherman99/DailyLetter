# The Daily Letter

[![Tests](https://github.com/christophersherman99/DailyLetter/actions/workflows/tests.yml/badge.svg)](https://github.com/christophersherman99/DailyLetter/actions/workflows/tests.yml)

An automated morning market letter built around my own portfolio, with a public companion dashboard.

**Dashboard:** https://christophersherman99.github.io/DailyLetter/

Every weekday a GitHub Actions job pulls market data, fundamentals, and news, runs the analytics
below, asks Claude to write the commentary from that data only, emails me the letter, saves the
day's numbers to `data/`, and rebuilds the dashboard. Everything public is in percentages: the
portfolio's dollar size and share counts never leave an encrypted repository secret.

## What's in it

| Section | What it does |
|---|---|
| **The Take** | Claude's summary of what drove the US, Europe, and Asia, grounded in the day's data and headlines, with memory of the last five letters |
| **Market Weather** | Rules-based Calm / Mixed / Stressed regime from seven signals: trend vs. the 200-day average, VIX and its term structure, breadth (equal- vs. cap-weight), chip-stock momentum as the AI-trade gauge, credit spreads, the yield curve, and safe-haven demand |
| **Portfolio** | Daily moves, weights, gain since purchase, unusual-move flags (moves scaled by each stock's own volatility), and headlines for holdings that moved |
| **Risk Check** | Beta, volatility, historical VaR, drawdowns, Sharpe ratio, correlations, and ETF look-through to true sector, region, and single-company exposure |
| **Stress tests** | Today's holdings replayed through the 2020 COVID crash, the 2022 bear market, the 2024 yen carry unwind, and the 2025 tariff shock, plus beta-based factor shocks and AI/big-tech exposure |
| **Shadow portfolio** | A conservative benchmark mix paper-traded beside the real one on the same risk and stress metrics |
| **Deep Dive** (Mondays) | A DCF valuation of one holding in rotation, led by a reverse DCF: the growth rate today's price implies |
| **What Moved** | The day's biggest moves among US companies worth $10B+, screened fresh each morning |

### Dashboard
- **Rebalancing simulator:** move weight between holdings and building blocks (gold, T-bills, bonds,
  staples, and more) and see volatility, beta, VaR, drawdown, AI exposure, and crash-replay results
  recalculate in the browser
- **DCF playground:** adjust growth, margins, discount rate, and terminal growth for any modeled holding;
  the reverse DCF solves for implied growth live
- **History:** performance vs. the S&P 500 and the shadow portfolio, the regime score and AI exposure over
  time, valuation history, and a searchable letter archive

## How it's built

| File | Role |
|---|---|
| `daily_letter.py` | Orchestrates the run: data, analytics, Claude commentary, HTML email |
| `regime.py` | Market regime signals and scoring |
| `risk.py` | Risk statistics and ETF look-through exposure |
| `stress.py` | Historical replays, factor shocks, AI exposure |
| `shadow.py` | Shadow portfolios from `shadows.csv`, run through the same risk and stress code |
| `dcf.py` | Valuation engine; also a CLI: `python dcf.py AAPL MSFT` |
| `history.py` | Percentages-only daily record in `data/`, read back for the AI's memory |
| `build_site.py` | Builds `site/data.json`; the dashboard in `site/` does the interactive math in JavaScript |
| `.github/workflows/daily.yml` | Weekday schedule: send, commit data, deploy to GitHub Pages |

Stack: Python (pandas, yfinance, matplotlib, feedparser), the Anthropic API (Claude Opus 5.5 with
structured JSON output), GitHub Actions, GitHub Pages, Chart.js.

## Methods in brief
- **VaR** is historical: the 5th-percentile daily return over the past year.
- **Look-through** weights each fund's sector mix and top ten holdings by its share of the portfolio, so
  single-company and AI exposure are floors.
- **Stress replays** apply each holding's actual return over a past window; funds that did not exist yet
  use a close stand-in (BIL for SGOV).
- **DCF:** ten-year two-stage unlevered free cash flow model. Analyst revenue growth for years one and
  two fades linearly to 2.5%; FCF margin is the 3-year median; WACC uses CAPM (10-year Treasury + beta x
  5% equity risk premium) and after-tax cost of debt at market weights; Gordon growth terminal value.
  Banks are skipped because debt is their raw material, not financing.
- **The AI** sees only the computed data, must not invent figures, writes percentages only, and never
  recommends trades.

## The data record
`data/` grows by one market day each morning: `portfolio.csv` (an index starting at 100, daily return,
risk stats, regime, AI exposure), `holdings.csv` (weights and returns), `markets.csv`, `shadows.csv`,
`valuations.csv`, and `letters.jsonl` (the AI's commentary).

## Running it
Holdings live in a `PORTFOLIO_CSV` repository secret (`ticker,shares,avg_cost` per line); locally, put the
same content in a git-ignored `portfolio.csv`. Then:
```
DRY_RUN=1 python daily_letter.py    # writes preview.html instead of emailing
python build_site.py                 # writes site/data.json
python dcf.py NVDA                   # value any company from the command line
```
Secrets for the scheduled job: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ANTHROPIC_API_KEY`, `PORTFOLIO_CSV`.

Not investment advice. Market data from Yahoo Finance and Google News may be delayed.
