#!/usr/bin/env python3
"""Read a salary band from a posting's text and suggest the figure to state.

A posting that names a band ("65.000 - 85.000 EUR", "€65k–€85k", "zwischen 4.500
und 6.000 Euro monatlich") gets a suggested Gehaltswunsch: 70% of the way up the
band, rounded to a full thousand, never above its top and never below the floor
(`salary_floor` in job_scraper/sweep_profile.json; no floor when unset). A band
that ends below the floor gets no suggestion, only a flag.

Why 70%: the stated figure is the screening number. Above the band's top a form
or a recruiter drops the application before anyone reads it; the upper third
still leaves room above what most candidates ask.

Single figures ("bis zu 85.000 €", "ab 60k") are reported but get no suggestion.

Some portals hand over the band as a field of their own, shown in their UI
rather than written in the text (LinkedIn's "Base pay range", StepStone's
salary payload, XING's teaser facts, Workwise, freehire, the Arbeitsagentur).
That field wins over the text. A portal's own estimate rather than the
employer's band is marked by its CLI ("(StepStone-Schätzung)", "(XING-Schätzung)")
and keeps that mark in the label: it is the market for the role, not the budget.

Usage:
  python3 tools/salary_band.py "Wir zahlen 65.000 - 85.000 EUR brutto im Jahr."
  python3 tools/salary_band.py --file posting.txt [--floor 60000]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path



def _profile_floor() -> int:
    path = Path(__file__).resolve().parent.parent / "job_scraper" / "sweep_profile.json"
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("salary_floor") or 0)
    except (OSError, ValueError):
        return 0


FLOOR = _profile_floor()
POSITION = 0.7  # how far up the band the suggested figure sits

_AMOUNT = r"\d{1,3}(?:[.,\u202f\u00a0 ]\d{3})+|\d{4,6}(?![.,]?\d)|\d{2,3}(?:[.,]\d)?"
_UNIT = r"\s?(?:k\b|tsd\.?|tausend|t€)"
_CUR = r"(?:€|eur(?:os?)?\b)"
_SEP = r"\s?(?:-|–|—|bis(?: zu)?|to|and|und)\s?"
RANGE = re.compile(
    rf"(?P<c1>{_CUR}\s?)?(?P<lo>{_AMOUNT})(?P<u1>{_UNIT})?\s?(?P<c2>{_CUR})?"
    rf"{_SEP}"
    rf"(?P<c3>{_CUR}\s?)?(?P<hi>{_AMOUNT})(?P<u2>{_UNIT})?\s?(?P<c4>{_CUR})?",
    re.I,
)
# Company figures, not pay: "50-100 Mio. €", "200-500 Mitarbeitende".
NOT_PAY = re.compile(r"^\s?(?:mio|mrd|million|billion|mitarbeit|employees|%)", re.I)
PAY_WORDS = re.compile(
    r"gehalt|vergütung|salary|compensation|brutto|\bgross\b|jahresziel|\bannual|per year|p\.\s?a\.|"
    r"\bpay\b|\bsalary range|gehaltsband|gehaltsspanne|verdienst|einkommen|\bote\b|\bbase\b", re.I)
MONTHLY = re.compile(r"monat|month|mtl\.|/\s?m\b|pro m\b", re.I)
# Not "Wochenstunden" or "40 hours per week": those sit next to yearly bands.
HOURLY = re.compile(r"pro stunde|per hour|hourly|stundenlohn|stundensatz|/\s?(?:h|hr|std)\b", re.I)
SINGLE = re.compile(
    rf"(?P<kind>bis zu|up to|max(?:imal)?\.?|ab|from|starting at|mindestens|at least)?\s?{_CUR}?\s?"
    rf"(?P<val>{_AMOUNT})(?P<u>{_UNIT})?\s?{_CUR}?", re.I)
_MAX_WORDS = ("bis zu", "up to", "max", "max.", "maximal")
_MIN_WORDS = ("ab", "from", "starting at", "mindestens", "at least")


def _value(raw: str, unit: str | None) -> float:
    digits = re.sub(r"[.,   ](?=\d{3}\b)", "", raw).replace(",", ".")
    value = float(digits)
    return value * 1000 if unit else value


def _context(text: str, start: int, end: int, width: int = 60) -> str:
    return text[max(0, start - width):end + width]


def _annual(lo: float, hi: float, around: str) -> tuple[float, float, str] | None:
    """The band as yearly euros, or None when it is not plausibly a salary."""
    if HOURLY.search(around):
        return None
    if 1_500 <= lo <= hi <= 15_000 and MONTHLY.search(around):
        return lo * 12, hi * 12, "month"
    if 20_000 <= lo <= hi <= 400_000:
        return lo, hi, "year"
    return None


def find_bands(text: str) -> list[dict]:
    """Every salary band in the text, yearly, in order of appearance."""
    text = re.sub(r"\s+", " ", text or "")
    bands, seen = [], set()
    for m in RANGE.finditer(text):
        if NOT_PAY.match(text[m.end():m.end() + 15]):
            continue
        u1, u2 = m.group("u1"), m.group("u2")
        lo, hi = _value(m.group("lo"), u1 or u2), _value(m.group("hi"), u2 or u1)
        if lo < 1_000 <= hi:  # "65 - 85.000 €"
            lo *= 1000
        has_cur = any(m.group(g) for g in ("c1", "c2", "c3", "c4", "u1", "u2"))
        around = _context(text, m.start(), m.end())
        if not (has_cur or PAY_WORDS.search(around)):
            continue
        annual = _annual(lo, hi, around)
        if not annual or annual[0] == annual[1]:
            continue
        key = annual[:2]
        if key in seen:
            continue
        seen.add(key)
        bands.append({"min": int(annual[0]), "max": int(annual[1]), "period": annual[2],
                      "quote": m.group(0).strip()})
    return bands


def find_single(text: str) -> dict | None:
    """A single figure when there is no band: one-sided ("bis zu 85.000 €",
    "ab 60k") or plain ("Compensation: 100,000 Euros")."""
    text = re.sub(r"\s+", " ", text or "")
    for m in SINGLE.finditer(text):
        value = _value(m.group("val"), m.group("u"))
        if not (20_000 <= value <= 400_000) or not (re.search(_CUR, m.group(0), re.I) or m.group("u")):
            continue
        # A plain figure needs a pay word right before it or a euro sign on it;
        # "190K+ GitHub stars" has neither.
        kind = (m.group("kind") or "").lower()
        before = text[max(0, m.start() - 40):m.start()] if not kind else _context(text, m.start(), m.end())
        if HOURLY.search(_context(text, m.start(), m.end())):
            continue
        if not (PAY_WORDS.search(before) or (not kind and re.search(_CUR, m.group(0), re.I))):
            continue
        side = "max" if kind in _MAX_WORDS else "min" if kind in _MIN_WORDS else "fix"
        return {side: int(value), "quote": m.group(0).strip()}
    return None


def suggest(band: dict, floor: int | None = None) -> int | None:
    """The figure to state for a band, or None when the band ends below the floor."""
    floor = FLOOR if floor is None else floor
    lo, hi = band["min"], band["max"]
    if hi < floor:
        return None
    wish = round((lo + POSITION * (hi - lo)) / 1000) * 1000
    return int(min(hi, max(floor, wish)))


def portal_bands(field: str | None) -> list[dict]:
    """A portal's own salary field ("62.000 € – 85.000 €", "65000–85000 €",
    "EUR 90000–120000/year", "4200–5100 EUR (Monatsgehalt)")."""
    if not field:
        return []
    # LinkedIn: "€70,000.00/yr - €90,000.00/yr"
    field = re.sub(r"(\d)[.,]00\b", r"\1", str(field))
    if "/yr" in field:
        field = field.replace("/yr", "") + " per year"
    lo_digits = [float(re.sub(r"[.,\u202f\u00a0 ](?=\d{3}\b)", "", n).replace(",", "."))
                 for n in re.findall(_AMOUNT, field)]
    # A bare monthly band carries no word saying so; the size does.
    monthly = lo_digits and max(lo_digits) <= 15_000 and not re.search(r"year|jahr|annual", field, re.I)
    return find_bands(f"Gehalt: {field}" + (" monatlich" if monthly else ""))


def assess(text: str, floor: int | None = None, portal_salary: str | None = None,
           portal: str | None = None) -> dict:
    """What /scrape shows in its salary column: the band, the suggestion, a flag.
    portal_salary is the portal's own salary field, read before the text."""
    from_portal = portal_bands(portal_salary)
    bands = from_portal or find_bands(text)
    if not bands:
        single = find_single(text)
        return {"band": None, "single": single, "wish": None, "below_floor": False,
                "label": _single_label(single) if single else ""}
    # Several bands (junior/senior, two cities): the highest one is the one to aim at.
    band = max(bands, key=lambda b: (b["max"], b["min"]))
    wish = suggest(band, floor)
    note = None
    if from_portal:
        marked = re.search(r"\(([^)]*schätzung)\)", str(portal_salary), re.I)
        note = marked.group(1) if marked else None
    return {"band": band, "bands": len(bands), "wish": wish, "below_floor": wish is None,
            "source": "portal" if from_portal else "text", "estimate": bool(note),
            "label": label(band, wish, floor) + (f" ({note})" if note else "")}


def _k(value: int) -> str:
    return f"{value / 1000:.1f}".rstrip("0").rstrip(".") + "k"


def label(band: dict, wish: int | None, floor: int | None = None) -> str:
    floor = FLOOR if floor is None else floor
    span = f"{_k(band['min'])}–{_k(band['max'])}"
    if band["period"] == "month":
        span += " (aus Monatswerten)"
    if wish is None:
        return f"{span} ⚠ unter {_k(floor)}"
    return f"{span} → {_k(wish)}"


def _single_label(single: dict) -> str:
    if "max" in single:
        return f"bis {_k(single['max'])}"
    return f"ab {_k(single['min'])}" if "min" in single else f"{_k(single['fix'])} genannt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", help="posting text (or use --file)")
    ap.add_argument("--file", type=Path)
    ap.add_argument("--floor", type=int, default=None, help="override the profile's salary_floor for this posting")
    args = ap.parse_args()
    text = args.file.read_text(encoding="utf-8") if args.file else args.text
    if not text:
        ap.error("give the posting text or --file")
    print(json.dumps(assess(text, args.floor), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
