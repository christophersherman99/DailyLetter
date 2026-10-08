"""Market regime: a rules-based read on whether the market is calm, mixed, or stressed.

Each signal is a simple, published-style rule with a reading and a plain-English reason.
Signals score 0 (ok), 1 (caution), or 2 (stress); the total sets the overall regime.
Nothing here predicts prices. It summarizes conditions that have historically mattered.
"""

TICKERS = {"spx": "^GSPC", "equal_weight": "RSP", "semis": "SMH", "vix": "^VIX",
           "vix3m": "^VIX3M", "high_yield": "HYG", "treasuries": "IEF", "gold": "GLD",
           "t10y": "^TNX", "t3m": "^IRX", "dollar": "DX-Y.NYB"}
OK, CAUTION, STRESS = 0, 1, 2
LEVELS = [(0, 2, "Calm"), (3, 5, "Mixed"), (6, 99, "Stressed")]


def _ret(s, days):
    return (float(s.iloc[-1]) / float(s.iloc[-days - 1]) - 1) * 100


def _vs_ma(s, days):
    return (float(s.iloc[-1]) / float(s.iloc[-days:].mean()) - 1) * 100


def _yield(s):
    v = float(s.iloc[-1])
    return v / 10 if v > 20 else v


def signals(data):
    """Evaluate every signal whose data is available. `data`: {ticker: daily close series}."""
    get = lambda key: data.get(TICKERS[key])
    out = []

    def add(name, level, reading, why):
        out.append({"name": name, "level": level, "reading": reading, "why": why})

    spx = get("spx")
    if spx is not None and len(spx) >= 200:
        gap = _vs_ma(spx, 200)
        level = STRESS if gap < 0 else CAUTION if gap < 2 or _vs_ma(spx, 50) < 0 else OK
        add("Trend", level, f"S&amp;P {abs(gap):.1f}% {'above' if gap >= 0 else 'below'} its "
            "200-day average", "Markets below their 200-day average have historically "
            "seen bigger and more frequent drops.")

    vix, vix3m = get("vix"), get("vix3m")
    if vix is not None:
        v = float(vix.iloc[-1])
        inverted = vix3m is not None and v > float(vix3m.iloc[-1])
        level = STRESS if v > 25 or inverted else CAUTION if v > 18 else OK
        add("Fear gauge", level, f"VIX {v:.1f}" + (", above 3-month VIX" if inverted else ""),
            "VIX measures expected volatility. Above 25, or short-term fear above "
            "longer-term fear, signals acute stress.")

    eq = get("equal_weight")
    if spx is not None and eq is not None and len(eq) > 63:
        gap = _ret(eq, 63) - _ret(spx, 63)
        level = STRESS if gap < -8 else CAUTION if gap < -4 else OK
        add("Breadth", level, f"Typical stock {gap:+.1f} pts vs the S&amp;P over 3 months",
            "When the equal-weight S&amp;P lags, gains rest on a few giants, which makes "
            "the market more fragile.")

    semis = get("semis")
    if semis is not None and len(semis) >= 200:
        stretch = _vs_ma(semis, 200)
        level = STRESS if stretch < 0 else CAUTION if stretch > 30 else OK
        state = ("below its 200-day average, the AI trade is losing momentum" if stretch < 0
                 else "far above its 200-day average, stretched" if stretch > 30
                 else "above its 200-day average")
        add("AI trade", level, f"Chip stocks (SMH) {abs(stretch):.0f}% {state}",
            "Semiconductors lead the AI trade. Very stretched or breaking down both tend "
            "to come before bigger swings.")

    hy, tsy = get("high_yield"), get("treasuries")
    if hy is not None and tsy is not None and len(hy) > 21:
        ratio = (hy / tsy.reindex(hy.index).ffill()).dropna()
        move = _ret(ratio, 21)
        level = STRESS if move < -3 else CAUTION if move < -1.5 else OK
        add("Credit", level, f"Junk bonds {move:+.1f}% vs Treasuries over a month",
            "Credit markets often sense trouble before stocks do. Junk bonds lagging "
            "Treasuries means lenders are getting nervous.")

    t10, t3m = get("t10y"), get("t3m")
    if t10 is not None and t3m is not None:
        spread = _yield(t10) - _yield(t3m)
        level = CAUTION if spread < 0 else OK
        add("Yield curve", level, f"10-year minus 3-month: {spread:+.2f} pts",
            "An inverted curve (short rates above long rates) has preceded most US "
            "recessions, usually with a long lag.")

    gold, dollar = get("gold"), get("dollar")
    if gold is not None and len(gold) > 63:
        g3 = _ret(gold, 63)
        d3 = _ret(dollar, 63) if dollar is not None and len(dollar) > 63 else 0.0
        level = CAUTION if g3 > 10 and d3 > 0 else OK
        add("Safe havens", level, f"Gold {g3:+.1f}% over 3 months, dollar {d3:+.1f}%",
            "Gold and the dollar rising together usually means investors are buying "
            "protection.")
    return out


def regime(data):
    sig = signals(data)
    score = sum(s["level"] for s in sig)
    name = next(n for lo, hi, n in LEVELS if lo <= score <= hi)
    return {"name": name, "score": score, "max": 2 * len(sig), "signals": sig,
            "flags": sum(1 for s in sig if s["level"])}
