"""Economic calendar parsers, run against snippets shaped like the real pages."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import econ  # noqa: E402

FED = """
<h4><a>2026 FOMC Meetings</a></h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>October</strong></div>
<div class="fomc-meeting__date col">27-28</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col">30-1*</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>December</strong></div>
<div class="fomc-meeting__date col">8-9</div></div>
<h4><a>2027 FOMC Meetings</a></h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>January</strong></div>
<div class="fomc-meeting__date col">26-27</div></div>
"""

BEA = """
<tr class="scheduled-releases-type-data"><td class="scheduled-date"><div class="release-date">October 22</div>
<small>10:00 AM</small></td><td>Data</td><td class="release-title">R&amp;D Statistics, 2024</td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date"><div class="release-date">October 29</div>
<small>8:30 AM</small></td><td>News</td><td class="release-title">GDP (Advance Estimate), 3rd Quarter 2026  </td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date"><div class="release-date">October 29</div>
<small>8:30 AM</small></td><td>News</td><td class="release-title">Personal Income and Outlays, September 2026</td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date"><div class="release-date">December 2</div>
<small>10:00 AM</small></td><td>News</td><td class="release-title">GDP by Industry, 2025</td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date"><div class="release-date">January 7</div>
<small>8:30 AM</small></td><td>News</td><td class="release-title">U.S. International Trade in Goods and Services, November 2026</td></tr>
"""


class Page:
    def __init__(self, text):
        self.text = text


def test_fed_decisions_fall_on_the_meetings_last_day(monkeypatch):
    monkeypatch.setattr(econ, "_get", lambda url, **kw: Page(FED))
    days = [d for d, _, _ in econ.fomc(date(2026, 1, 1))]
    assert days == [date(2026, 10, 28), date(2026, 5, 1), date(2026, 12, 9), date(2027, 1, 27)]


def test_bea_keeps_market_moving_releases_and_rolls_the_year(monkeypatch):
    monkeypatch.setattr(econ, "_get", lambda url, **kw: Page(BEA))
    events = econ.bea(date(2026, 10, 21))
    names = [e for _, e, _ in events]
    assert names == ["GDP, 3rd Quarter 2026 (advance estimate)",
                     "PCE inflation and spending, September 2026",
                     "Trade balance, November 2026"]
    assert events[-1][0] == date(2027, 1, 7)  # January on a late-year schedule means next year
    assert all(why for _, _, why in events)
