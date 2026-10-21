"""Catalyst headline tagging: real headline shapes and the false positives they replaced."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import catalysts  # noqa: E402


@pytest.mark.parametrize("title, kind", [
    ("FDA approves GSK's hepatitis B drug, offering patients chance to stop treatment", "FDA"),
    ("Veradermics Soars 10% as Phase 3 Data Show Oral Hair-Loss Pill Could Transform Treatment", "Trial"),
    ("Arcus stock tumbles 6% after unveiling casdatifan trial data", "Trial"),
    ("Salesforce to acquire Braze for $5.66bn in customer experience push", "Deal"),
    ("Cencora to buy American Oncology Network in $2.4 billion deal", "Deal"),
    ("Apple raises full-year outlook on iPhone demand", "Guidance"),
    ("Telix Pharmaceuticals Q3 Revenue Rises 19%", "Earnings"),
    ("Earnings To Watch: Barclays PLC Q3 2026", "Earnings"),
    ("Alphabet beats estimates as cloud growth accelerates", "Earnings"),
    ("Dexcom CEO steps down effective immediately", "Leadership"),
    ("How Private Credit Probe At Barclays Has Changed Its Investment Story", "Legal"),
    ("McDonald's announces $5 billion buyback", "Capital"),
])
def test_headlines_get_the_right_tag(title, kind):
    assert catalysts.classify(title) == kind


@pytest.mark.parametrize("title", [
    "GRAIL Stock Sees Fair Value Lift After Analysts Back Galleri Outlook",  # analysts, not company
    "Amazon Trades at 24 Times Forward Earnings. Can Its Cash Engines Fund the Robotaxi Bet?",
    "3 Stocks to Watch This Week",
])
def test_non_events_stay_untagged(title):
    assert catalysts.classify(title) is None


def test_headline_must_name_the_company():
    assert catalysts._about("Arcus stock tumbles after trial data", "RCUS", "Arcus Biosciences")
    assert not catalysts._about("High-yield dividend bundle to buy", "ASST", "Strive, Inc.")


def test_duplicate_stories_from_different_outlets_are_dropped():
    items = [{"title": "Cencora to buy American Oncology Network in $2.4 billion deal - Reuters"},
             {"title": "Cencora to acquire American Oncology Network in $2.4 billion deal - KSL"},
             {"title": "CBRE to acquire Onnec in $1 billion data center deal - TechTarget"}]
    assert len(catalysts._dedupe(items)) == 2
