"""The Weekly Wrap: a Saturday edition covering the full trading week.

Performance attribution: each holding's contribution, in percentage points, is its weight at
the start of the week times its return over the week, so the contributions add up to the
portfolio's weekly return.
"""
import json
import os
from datetime import date, datetime, timedelta
from html import escape

import pandas as pd

import daily_letter as dl
import earnings
import history
import shadow

WEEKLY = os.path.join(history.DATA, "weekly.jsonl")
WEEK_SCHEMA = {
    "type": "object",
    "properties": {
        "take": {"type": "string"},
        "lesson_title": {"type": "string"},
        "lesson": {"type": "string"},
        "next_week": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["take", "lesson_title", "lesson", "next_week"],
    "additionalProperties": False,
}
WEEK_SYSTEM = """You write the AI sections of a Saturday weekly wrap for a market letter. The \
reader is a college student interested in global markets, prime brokerage and Asia, who owns \
the portfolio shown and is learning finance.

Fill four fields:
- take: 5 to 6 sentences on the week: what drove markets across regions and sectors, how the \
portfolio did against the S&P 500 and the reader's Conservative benchmark, and which holdings \
explain the difference. Use the daily letters for the week's storyline.
- lesson_title: a short title (under 8 words) for one finance concept this week illustrated.
- lesson: 2 to 3 sentences teaching that concept plainly, tied to something that happened this \
week (for example why a stock can fall on an earnings beat, what a falling VIX means, or why \
small caps lag when yields rise).
- next_week: 2 to 4 short items to watch next week, from the calendar and earnings provided.

Rules: use only the data given. Never invent figures or causes; say "likely" for inferences. \
Describe the reader's portfolio only in percentages, never dollars. No buy, sell or hold \
recommendations. Plain, specific language. No hype, no em dashes, no bullet characters inside \
the strings."""


def week_bounds(spx, today):
    """(reference close date before the week, last close of the week)."""
    end = spx.index[spx.index.date <= today][-1]
    monday = end - timedelta(days=end.weekday())
    ref = spx.index[spx.index < monday][-1]
    return ref, end


def ret(s, ref, end):
    s = s.dropna()
    a, b = s[s.index <= ref], s[s.index <= end]
    return (float(b.iloc[-1]) / float(a.iloc[-1]) - 1) * 100 if len(a) and len(b) else None


def attribution(holdings, data, ref, end):
    """Each holding's weekly return and contribution (percentage points)."""
    rows, start_total = [], 0.0
    for h in holdings:
        t = h["ticker"]
        if t in dl.CASH:
            start, r = h["shares"], 0.0
        elif t in data:
            s = data[t]
            start = h["shares"] * float(s[s.index <= ref].iloc[-1])
            r = ret(s, ref, end)
        else:
            continue
        rows.append({"ticker": t, "start": start, "ret": r or 0.0, "cash": t in dl.CASH})
        start_total += start
    for r in rows:
        r["weight"] = r["start"] / start_total * 100
        r["contrib"] = r["weight"] * r["ret"] / 100
    rows.sort(key=lambda r: -r["contrib"])
    return rows, sum(r["contrib"] for r in rows)


def _rows_in_week(name, ref, end):
    path = os.path.join(history.DATA, f"{name}.csv")
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, dtype={"date": str})
    return df[(df["date"] > str(ref.date())) & (df["date"] <= str(end.date()))].to_dict("records")


def build(today=None):
    today = today or datetime.now(dl.ET).date()
    holdings = dl.load_portfolio()
    held = [h["ticker"] for h in holdings if h["ticker"] not in dl.CASH]
    world_tickers = [t for rows in dl.WORLD.values() for t in rows.values()]
    data = dl.download(held + world_tickers + list(dl.SECTORS.values()) + shadow.tickers()
                       + list(dl.MACRO.values()))
    spx = data["^GSPC"]
    ref, end = week_bounds(spx, today)

    rows, you = attribution(holdings, data, ref, end)
    shadows = {name: sum(w * (ret(data[t], ref, end) or 0) for t, w in p["weights"].items()
                         if t in data) for name, p in shadow.load().items()}
    world = {region: {n: ret(data[t], ref, end) for n, t in items.items() if t in data}
             for region, items in dl.WORLD.items()}
    sectors = {n: {"day": ret(data[t], ref, end)} for n, t in dl.SECTORS.items() if t in data}
    macro = {n: ret(data[t], ref, end) for n, t in dl.MACRO.items() if t in data and t != "^TNX"}
    tnx = data.get("^TNX")
    tnx_bps = None
    if tnx is not None:
        scale = 10 if float(tnx.iloc[-1]) > 20 else 1
        tnx_bps = (float(tnx[tnx.index <= end].iloc[-1]) - float(tnx[tnx.index <= ref].iloc[-1])) / scale * 100

    daily = _rows_in_week("portfolio", ref, end)
    regimes = [(d["date"], d.get("regime")) for d in daily if isinstance(d.get("regime"), str)]
    cats = [c for c in _rows_in_week("catalysts", ref, end) if c["source"] in ("holding", "watchlist")]
    results = [e for e in _rows_in_week("earnings", ref, end) if e["kind"] == "result"]
    results = list({e["ticker"]: e for e in results}.values())
    letters = [e for e in history.load_letters() if str(ref.date()) < e["date"] <= str(end.date())]

    ahead = earnings.scan(held, data, today=today)["previews"]
    previewed = {f"{a['ticker']} earnings" for a in ahead}  # the preview row says more
    events = [(d, e) for d, e in dl.calendar(holdings)
              if d <= today + timedelta(days=9) and e not in previewed]
    return {"ref": ref.date(), "end": end.date(), "you": you, "rows": rows,
            "spx": world["US"].get("S&P 500"), "shadows": shadows, "world": world,
            "sectors": sectors, "macro": macro, "tnx_bps": tnx_bps, "regimes": regimes,
            "catalysts": cats, "results": results, "letters": letters, "ahead": ahead,
            "events": events}


def brief(w):
    L = [f"WEEK: {w['end'] - timedelta(days=w['end'].weekday())} to {w['end']}",
         f"PORTFOLIO {w['you']:+.2f}% vs S&P 500 {w['spx']:+.2f}%"
         + "".join(f", {n} benchmark {v:+.2f}%" for n, v in w["shadows"].items()),
         "ATTRIBUTION (weekly return, contribution in pts):"]
    L += [f"  {r['ticker']}: {r['ret']:+.2f}%, {r['contrib']:+.2f} pts" for r in w["rows"] if not r["cash"]]
    L.append("WORLD (week): " + "; ".join(f"{reg} " + ", ".join(f"{n} {v:+.1f}%" for n, v in items.items()
                                                              if v is not None)
                                          for reg, items in w["world"].items()))
    L.append("SECTORS (week): " + ", ".join(f"{n} {q['day']:+.1f}%" for n, q in w["sectors"].items()
                                           if q["day"] is not None))
    L.append("RATES, FX, COMMODITIES (week): " + ", ".join(f"{n} {v:+.1f}%" for n, v in w["macro"].items()
                                                          if v is not None)
             + (f", US 10Y {w['tnx_bps']:+.0f} bps" if w["tnx_bps"] is not None else ""))
    if w["regimes"]:
        L.append("MARKET REGIME by day: " + ", ".join(f"{d} {r}" for d, r in w["regimes"]))
    L += ["CATALYSTS: " + c["ticker"] + f" [{c['type']}] {c['headline']}" for c in w["catalysts"][:8]]
    L += [f"EARNINGS RESULT: {e['ticker']} EPS {e['eps']} vs {e['eps_est']}, reaction {e['reaction_pct']}%"
          for e in w["results"]]
    L += [f"EARNINGS NEXT: {p['ticker']} {p['date']} {p['timing']}" for p in w["ahead"]]
    L += [f"CALENDAR: {d} {e}" for d, e in w["events"]]
    L.append("THIS WEEK'S DAILY LETTERS:")
    L += [f"  {e['date']}: {e['take']}" for e in w["letters"] if e.get("take")]
    return "\n".join(L)


def ai(text):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    client = anthropic.Anthropic()
    try:
        r = client.beta.messages.create(
            model=dl.MODEL, max_tokens=8000, betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": WEEK_SCHEMA}},
            system=WEEK_SYSTEM, messages=[{"role": "user", "content": text}])
        if r.stop_reason != "end_turn":
            print("Weekly AI skipped, stop reason:", r.stop_reason)
            return None
        return json.loads(next(b.text for b in r.content if b.type == "text"))
    except Exception as e:
        print("Weekly AI skipped:", e)
        return None


def html(w, take):
    S, D = dl.SANS, dl.SERIF
    start = w["end"] - timedelta(days=w["end"].weekday())  # Monday of the week
    p = [f"<div style='font-family:{S};font-size:11px;letter-spacing:1.6px;text-transform:uppercase;"
         f"color:{dl.MUTED}'>Week of {start:%B} {start.day}, {start.year}</div>"
         f"<div style='font-family:{D};font-size:34px;line-height:1.15;color:{dl.INK};margin:6px 0 14px'>"
         "The Weekly Wrap</div><div style='border-top:3px double " + dl.INK + "'></div>"]
    if take:
        p.append(dl.label("The Week", top=False).replace("margin-bottom:12px", "margin:24px 0 10px"))
        p.append(f"<div style='font-family:{D};font-size:17px;line-height:1.65;color:{dl.INK}'>"
                 f"{escape(take['take'])}</div>")

    tiles = [dl.tile("You", dl.signed(w["you"], "{:+.2f}%"), "this week"),
             dl.tile("S&amp;P 500", dl.signed(w["spx"], "{:+.2f}%"), "this week")]
    tiles += [dl.tile(escape(n), dl.signed(v, "{:+.2f}%"), "your par") for n, v in list(w["shadows"].items())[:1]]
    p.append(dl.label("Scoreboard", link=dl.dash(anchor="history")))
    p.append(f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
             f"style='border-collapse:collapse;margin:0 -4px'><tr>{''.join(tiles)}</tr></table>")

    p.append(dl.caption("Attribution: how many points of your week each holding contributed"))
    biggest = max((abs(r["contrib"]) for r in w["rows"]), default=1) or 1
    p.append(f"{dl.TABLE}<tr>{dl.th('Holding', 'left')}{dl.th('Week')}{dl.th('Weight')}{dl.th('Contribution', 'left')}</tr>")
    for r in w["rows"]:
        if r["cash"]:
            continue
        width = abs(r["contrib"]) / biggest * 70
        color = dl.UP if r["contrib"] >= 0 else dl.DOWN
        bar = (f"<span style='display:inline-block;width:{width:.0f}px;height:6px;background:{color};"
               f"border-radius:2px;vertical-align:middle;margin-right:6px'></span>"
               f"{dl.signed(r['contrib'], '{:+.2f} pts')}")
        p.append(f"<tr>{dl.td('<b>' + r['ticker'] + '</b>', 'left')}{dl.td(dl.signed(r['ret']))}"
                 f"{dl.td(f'{r['weight']:.0f}%')}{dl.td(bar, 'left', 'padding-left:14px')}</tr>")
    p.append("</table>")

    p.append(dl.label("Markets This Week"))
    p.append(f"{dl.TABLE}<tr>{dl.th('', 'left')}{dl.th('Week')}</tr>")
    for region, items in w["world"].items():
        p.append(f"<tr><td colspan='2' style='padding:12px 0 2px;font-family:{D};font-size:15px'>{region}</td></tr>")
        p += [f"<tr>{dl.td(n, 'left')}{dl.td(dl.signed(v))}</tr>" for n, v in items.items() if v is not None]
    p.append("</table>")
    p.append(dl.caption("US sectors this week").replace("margin:18px 0 6px", "margin:16px 0 6px"))
    p.append("<img src='cid:sectors' width='100%' alt='US sector moves this week' "
             "style='display:block;width:100%;height:auto'>")
    if w["regimes"]:
        seq = " &rarr; ".join(f"{date.fromisoformat(d):%a} {r}" for d, r in w["regimes"])
        p.append(f"<div style='{dl.NUM};font-size:12.5px;color:{dl.MUTED};margin-top:10px'>"
                 f"Market Weather: {seq}</div>")

    if w["catalysts"] or w["results"]:
        p.append(dl.label("Events This Week", link=dl.dash(anchor="catalysts")))
        for e in w["results"]:
            beat = e.get("surprise_pct") is not None and e["surprise_pct"] >= 0
            p.append(f"<div style='font-family:{S};font-size:13.5px;margin-bottom:8px'>{dl.tag('Results')}"
                     f"&nbsp; <b>{e['ticker']}</b> EPS ${e['eps']:.2f} vs ${e['eps_est']:.2f} "
                     f"({'beat' if beat else 'miss'}), stock "
                     + (dl.signed(e['reaction_pct']) if e.get('reaction_pct') is not None else "n/a")
                     + "</div>")
        seen = set()
        for c in w["catalysts"]:
            if c["headline"] in seen:
                continue
            seen.add(c["headline"])
            p.append(f"<div style='margin-bottom:8px'>{dl.tag(c['type'] or 'News')}&nbsp; "
                     f"<b style='font-family:{S};font-size:13px'>{c['ticker']}</b>&nbsp; "
                     f"{dl.link(c['headline'], c['link'], 14) if c.get('link') else escape(c['headline'])}</div>")

    if (take and take["next_week"]) or w["ahead"] or w["events"]:
        p.append(dl.label("Next Week"))
        if take:
            p += [f"<div style='font-family:{D};font-size:15.5px;line-height:1.55;padding-left:12px;"
                  f"border-left:2px solid {dl.ACCENT};margin-bottom:10px'>{escape(x)}</div>"
                  for x in take["next_week"]]
        rows = [(date.fromisoformat(a["date"]), f"{a['ticker']} earnings, {a['timing']}"
                 + (f" (options imply &plusmn;{a['implied']['pct']:.1f}%)" if a["implied"] else ""))
                for a in w["ahead"]] + [(d, escape(e)) for d, e in w["events"]]
        if rows:
            p.append(dl.TABLE + "".join(
                f"<tr>{dl.td(f'{d:%a %b} {d.day}', 'left', f'width:92px;color:{dl.MUTED};font-size:12.5px')}"
                f"{dl.td(e, 'left', 'white-space:normal')}</tr>" for d, e in sorted(set(rows))) + "</table>")

    if take and take.get("lesson"):
        p.append(dl.label("Lesson of the Week"))
        p.append(f"<div style='background:{dl.PAPER};border:1px solid {dl.RULE};padding:14px 16px'>"
                 f"<div style='font-family:{D};font-size:18px;color:{dl.INK};margin-bottom:6px'>"
                 f"{escape(take['lesson_title'])}</div><div style='font-family:{D};font-size:15px;"
                 f"line-height:1.6;color:#3d3a35'>{escape(take['lesson'])}</div></div>")

    p.append(f"<div style='border-top:1px solid {dl.RULE};margin-top:30px;padding-top:14px;"
             f"font-family:{S};font-size:11px;line-height:1.6;color:{dl.FAINT}'>Weekly returns use "
             "today's holdings from the prior Friday's close. Contribution = starting weight x weekly "
             "return. Written by Claude from this data only. Not investment advice.</div>")
    body = "".join(p)
    return (f"<div style='background:{dl.PAPER};padding:24px 10px'><table role='presentation' "
            f"align='center' width='100%' cellpadding='0' cellspacing='0' style='max-width:620px;"
            f"background:{dl.CARD};border:1px solid {dl.RULE}'><tr><td style='padding:30px 26px 26px'>"
            f"{body}</td></tr></table></div>")


def save(w, take):
    entries = []
    if os.path.exists(WEEKLY):
        with open(WEEKLY, encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
    entry = {"week_end": str(w["end"]), "you_pct": round(w["you"], 3),
             "spx_pct": round(w["spx"], 3) if w["spx"] is not None else None,
             "shadows": {k: round(v, 3) for k, v in w["shadows"].items()},
             "contributions": [{"ticker": r["ticker"], "pts": round(r["contrib"], 3)}
                               for r in w["rows"] if not r["cash"]],
             "take": take and history.scrub(take["take"]),
             "lesson_title": take and take["lesson_title"],
             "lesson": take and history.scrub(take["lesson"]),
             "next_week": take and history.scrub(take["next_week"])}
    existing = next((e for e in entries if e["week_end"] == entry["week_end"]), None)
    if not take and existing and existing.get("take"):
        for k in ("take", "lesson_title", "lesson", "next_week"):
            entry[k] = existing.get(k)
    entries = [e for e in entries if e["week_end"] != entry["week_end"]] + [entry]
    os.makedirs(history.DATA, exist_ok=True)
    with open(WEEKLY, "w", encoding="utf-8") as f:
        for e in sorted(entries, key=lambda e: e["week_end"]):
            f.write(json.dumps(e) + "\n")


def main():
    w = build()
    text = brief(w)
    take = ai(text)
    page = html(w, take)
    start = w["end"] - timedelta(days=w["end"].weekday())  # Monday of the week
    subject = (f"Weekly Wrap | Week of {start:%b} {start.day} | You {w['you']:+.2f}%, "
               f"S&P {w['spx']:+.2f}%")
    images = {"sectors": dl.sector_chart(w["sectors"])}
    plain = f"The Weekly Wrap\nYou {w['you']:+.2f}%, S&P {w['spx']:+.2f}%\n\n" + (take["take"] if take else "")
    if os.environ.get("DRY_RUN"):
        with open(os.path.join(dl.HERE, "preview.html"), "w", encoding="utf-8") as f:
            f.write(f"<meta charset='utf-8'><title>{escape(subject)}</title><body style='margin:0'>"
                    + page.replace("cid:sectors", "sectors.png") + "</body>")
        with open(os.path.join(dl.HERE, "sectors.png"), "wb") as f:
            f.write(images["sectors"])
        with open(os.path.join(dl.HERE, "brief.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        print("Preview written:", subject)
    else:
        dl.send(subject, page, plain, images)
        print("Sent:", subject)
        save(w, take)
        print("Saved weekly wrap for", w["end"])


if __name__ == "__main__":
    main()
