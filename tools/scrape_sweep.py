#!/usr/bin/env python3
"""Exhaustive portal sweep for /scrape: every posting in the window, not a sample.

/scrape used to send a handful of keyword queries per portal and read page 1 of
each. Measured on 2026-10-26, that lost postings on almost every portal:

  * LinkedIn returns 10 cards per page; all 23 queries of a run stopped at
    exactly 10, and pages 2-4 of two of them held 30 postings no run had seen.
  * StepStone (22 of 27 queries) and freehire (10 of 10) stopped at their page
    size too.
  * StepStone and the Arbeitsagentur silently ignore unsupported day counts:
    `--jobage 2` returned every posting regardless of age.
  * The Arbeitsagentur's `homeoffice` filter returns 0 results, always.
  * Instaffo's sitemap stamps every posting with today's date, so its age
    filter kept almost nothing; Workwise's dropped undated postings.

This tool replaces the hand-picked queries with a measured plan (PLAN below):
per portal, the searches that cover the user's search areas and fully remote
roles in Germany, each paged until the portal has nothing more. Areas,
keywords, title filters and triage weights come from the search profile
job_scraper/sweep_profile.json (template: tools/sweep_profile.example.json). The
window comes from job_scraper/sweep_state.json (the last successful sweep of
each portal), so a skipped or failed run is caught up on the next one. A sweep
only records its time as pending; `--confirm`, run after /scrape has stored
the results, makes it count. A session that dies in between leaves the old
window in place, and the next run reads it again.

It writes, for the skill to act on:
  <out>/sweep_candidates.json  new postings that pass the relevance filter:
                               these get the fit check
  <out>/sweep_skipped.json     new postings that do not (retail, trades,
                               apprenticeships ...), for
                               `seen_jobs.py index` (fingerprints only)
  <out>/sweep_report.json      per portal and search: pages, results, the
                               portal's total, whether it ran out or hit a cap,
                               and any error, verbatim

The relevance filter only reads titles and is deliberately generous: checked
against every posting ever rated high/medium or ranked in seen_jobs.json and
every tracker row, it drops none of them (tests/test_scrape_sweep.py pins this).

Usage:
  python3 tools/scrape_sweep.py --out out
  python3 tools/scrape_sweep.py --out out --days 3 --portals linkedin,stepstone
  python3 tools/scrape_sweep.py --out out --no-state     # measuring, not scraping
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seen_jobs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "job_scraper" / "sweep_state.json"
SKILLS = ROOT / ".agents" / "skills"

DEFAULT_DAYS = 3  # first run, or a portal with no recorded success
# A three-week holiday must not lose its first week. Past 14 days StepStone
# and past 28 the Arbeitsagentur have no day filter left and read every
# posting of any age (the client-side date filter still applies), so a long
# window is slow but complete; the report flags anything past LONG_DAYS.
MAX_DAYS = 30
LONG_DAYS = 14

# The search profile: everything that depends on who is searching (areas,
# keywords, title filters, weights). The portal mechanics below do not.
PROFILE_FILE = ROOT / "job_scraper" / "sweep_profile.json"
PROFILE_EXAMPLE = Path(__file__).resolve().parent / "sweep_profile.example.json"


def load_profile(path: Path | None = None) -> dict:
    """The user's profile, or the example when none exists yet (imports and
    tests); main() refuses to sweep without the user's own."""
    path = path or (PROFILE_FILE if PROFILE_FILE.is_file() else PROFILE_EXAMPLE)
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE = load_profile()


def build_plan(profile: dict) -> dict[str, dict]:
    """One entry per portal, one search per area and pass. `pages`: a hard stop
    that is only ever reached when the portal misbehaves (a correct sweep ends
    on an empty page or the portal's own total first); hitting it is reported
    as "capped", never passed off as done. Portals without a search are left out."""
    areas = profile.get("areas") or []
    remote = bool(profile.get("remote"))
    radius = lambda a: str(a.get("radius_km", 30))  # noqa: E731
    fields = ";".join(profile.get("arbeitsagentur_fields") or [])
    xing_keywords = profile.get("xing_keywords") or []
    plan = {
        "linkedin": {
            "page_size": 10, "pages": 100, "delay": 1.0,
            "window": "minutes",
            # The guest search ignores f_F job-function filters for recall: with
            # f_F=it it lost relevant engineering titles, so areas run unfiltered.
            "searches": [{"pass": "corridor", "args": ["-l", a.get("linkedin") or f"{a['name']}, Germany"]}
                         for a in areas]
            # Remote cannot be swept whole: LinkedIn stops at 1,000 results per
            # search and one day of remote postings in Germany is far more. So
            # remote runs per role keyword, each read to the end over the exact window.
            + ([{"pass": "remote", "args": ["-l", "Germany", "--remote", "remote", "-q", k]}
                for k in profile.get("linkedin_remote_keywords") or []] if remote else []),
        },
        "stepstone": {
            "page_size": 25, "pages": 400, "delay": 0.3,
            # age_1 is "today" or "24 h", undocumented either way: read 3 days.
            "window": "jobage", "min_days": 3,
            "searches": [{"pass": "corridor", "args": ["-l", a["name"], "--radius", radius(a)]} for a in areas]
            + ([{"pass": "remote", "args": ["-l", "Deutschland", "--remote", "remote"]}] if remote else []),
        },
        "arbeitsagentur": {
            "page_size": 50, "pages": 200, "delay": 0.1,
            # veroeffentlichtseit=1 has unclear edges and the API is fast, so read the 7-day bucket.
            "window": "jobage", "min_days": 7,
            "searches": ([{"pass": "corridor", "args": ["--field", fields, "-l", a["name"], "-r", radius(a)]}
                          for a in areas]
                         # No remote filter exists on this API; keep "Homeoffice möglich" only.
                         + ([{"pass": "remote", "args": ["--field", fields], "keep": "homeoffice"}] if remote else []))
            if fields else [],
        },
        "xing": {
            # XING serves at most 50 pages (1,000 hits) and reshuffles its order
            # between requests. Narrow, overlapping keywords keep each search
            # under the ceiling and catch what one shuffle drops. XING does not
            # split German compounds, so list compounds as keywords of their own.
            "page_size": 20, "pages": 55, "delay": 0.3, "stale_stop": False,
            "window": "client",
            "searches": [{"pass": "corridor", "args": ["-q", k, "-l", a["name"], "--radius", radius(a)]}
                         for a in areas for k in xing_keywords]
            + ([{"pass": "remote", "args": ["-q", k, "--remote", "remote"]} for k in xing_keywords] if remote else []),
        },
        "freehire": {
            "page_size": 100, "pages": 50, "delay": 0.2,
            "window": "jobage", "min_days": 2,
            # freehire's city facet is exact, not a radius.
            "searches": ([{"pass": "corridor", "args": ["--city", ",".join(profile["freehire_cities"]),
                                                        "-n", "100", "--no-description"]}]
                         if profile.get("freehire_cities") else [])
            + ([{"pass": "remote", "args": ["--country", "DE", "--remote", "remote", "-n", "100",
                                            "--no-description"]}] if remote else []),
        },
        "workwise": {
            "page_size": 25, "pages": 40, "delay": 0.3,
            # The search API carries no date; dedup against seen_jobs.json decides.
            "window": "none",
            "searches": [{"pass": "corridor", "args": ["-l", a["name"], "--radius", radius(a)]} for a in areas]
            + ([{"pass": "remote", "args": ["--remote", "remote"]}] if remote else []),
        },
        "instaffo": {
            # The whole board in one sitemap request; new postings are hydrated
            # with `detail` (company, location, date) before they count.
            "window": "none", "index": True, "delay": 0.3,
            "searches": [{"pass": "index", "args": []}],
        },
    }
    return {portal: entry for portal, entry in plan.items() if entry["searches"]}


PLAN: dict[str, dict] = build_plan(PROFILE)

# --- relevance -------------------------------------------------------------

# Title filters from the profile. RELEVANT is the wide net, EXCLUDED always
# drops (internships, apprenticeships ...), CORE marks the titles that get the
# fit check; the rest of RELEVANT ("edge") only gets a title skim.
RELEVANT = re.compile(PROFILE["relevant"], re.I)
EXCLUDED = re.compile(PROFILE.get("excluded") or r"(?!x)x", re.I)
CORE = re.compile(PROFILE.get("core") or PROFILE["relevant"], re.I)


def is_relevant(title: str | None) -> bool:
    title = title or ""
    return bool(RELEVANT.search(title)) and not EXCLUDED.search(title)


def tier(title: str | None) -> str:
    return "core" if CORE.search(title or "") else "edge"


# Only for rows that come from a board-wide index (Instaffo), where no search
# restricted the area: the profile's areas and freehire places, or remote.
def _corridor(profile: dict) -> re.Pattern:
    places = [a["name"] for a in profile.get("areas") or []] + list(profile.get("freehire_cities") or [])
    words = list(dict.fromkeys(re.escape(p.lower()) for p in places))
    if profile.get("remote"):
        words += ["remote", r"home.?office", "deutschlandweit", "bundesweit"]
    return re.compile("|".join(words) or r"(?!x)x", re.I)


CORRIDOR = _corridor(PROFILE)


# --- triage ------------------------------------------------------------------
#
# A 3-day sweep holds thousands of relevant titles; reading every posting is
# not possible (one request and ~1,500 tokens each). The score orders them by
# the profile's weights so the strongest are read in full automatically
# (AUTO_READ), and every other title is still looked at in the title list. The
# weights mirror CLAUDE.md: target stacks and roles up, roles the user does not
# want down. tests/test_scrape_sweep.py checks them against every posting ever
# rated a fit, once there is a history.

SCORE = [(re.compile(p, re.I), w) for p, w in PROFILE.get("score") or []]
_preferred = PROFILE.get("preferred_location") or {}
PREFERRED = re.compile(_preferred["pattern"], re.I) if _preferred.get("pattern") else None
PREFERRED_BONUS = int(_preferred.get("bonus", 3))

# Read in full without asking: core titles in the search areas from this score
# up, remote ones from the (usually higher) remote line, since remote is most of
# the volume and leaks hybrid roles.
AUTO_READ = {"corridor": 5, "remote": 11} | (PROFILE.get("auto_read") or {})


# An optional ranking of wished-for employers (a markdown table, e.g. made for
# speculative applications) nudges their postings up, so they reach the full
# read sooner; it never filters. Kept small on purpose: the role decides, the
# employer only tips a borderline title.
EMPLOYER_LIST = ROOT / PROFILE["employer_list"] if PROFILE.get("employer_list") else ROOT / "company_research" / "employers.md"
EMPLOYER_BONUS = {"Strong": 2, "Good": 2, "Moderate": 1}
GENERIC_NAMES = {"holding", "gruppe", "group", "netz", "gmbh"}


def load_employers(path: Path = EMPLOYER_LIST) -> list[tuple[re.Pattern, int, bool]]:
    """(matcher, bonus, whole-word) per employer alias from the list's ranking table."""
    if not path.is_file():
        return []
    rows = re.findall(r"^\|\s*\d+\s*\|[^|]+\|\s*(Strong|Good|Moderate|Weak)[^|]*\|\s*([^|]+)\|",
                      path.read_text(encoding="utf-8"), re.M)
    out = []
    for band, cell in rows:
        name = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)
        if band not in EMPLOYER_BONUS or " via " in name:  # a recruiter route names no employer
            continue
        name = re.sub(r"\([^)]*\)|[\"“”]", " ", name)
        for alias in re.split(r"\s*(?:/|>|-(?=[A-Z]{2,}\b))\s*", name):
            key = seen_jobs.norm_company(alias)
            if not key or key in GENERIC_NAMES:
                continue
            # Short names (EWE, OLB, PSI) only as a whole word; longer ones inside the name.
            rx = re.compile(rf"\b{re.escape(alias.strip().lower())}\b" if len(key) < 5 else re.escape(key))
            out.append((rx, EMPLOYER_BONUS[band], len(key) < 5))
    return out


EMPLOYERS = load_employers()


def apply_profile(profile: dict) -> None:
    """Rebuild everything derived from the profile (tests swap in the example)."""
    global PROFILE, PLAN, RELEVANT, EXCLUDED, CORE, CORRIDOR, SCORE, PREFERRED, PREFERRED_BONUS
    global AUTO_READ, EMPLOYER_LIST, EMPLOYERS
    PROFILE, PLAN = profile, build_plan(profile)
    RELEVANT = re.compile(profile["relevant"], re.I)
    EXCLUDED = re.compile(profile.get("excluded") or r"(?!x)x", re.I)
    CORE = re.compile(profile.get("core") or profile["relevant"], re.I)
    CORRIDOR = _corridor(profile)
    SCORE = [(re.compile(p, re.I), w) for p, w in profile.get("score") or []]
    preferred = profile.get("preferred_location") or {}
    PREFERRED = re.compile(preferred["pattern"], re.I) if preferred.get("pattern") else None
    PREFERRED_BONUS = int(preferred.get("bonus", 3))
    AUTO_READ = {"corridor": 5, "remote": 11} | (profile.get("auto_read") or {})
    EMPLOYER_LIST = (ROOT / profile["employer_list"] if profile.get("employer_list")
                     else ROOT / "company_research" / "employers.md")
    EMPLOYERS = load_employers(EMPLOYER_LIST)


def employer_bonus(company: str | None) -> int:
    raw, key = str(company or "").lower(), seen_jobs.norm_company(company)
    return max((bonus for rx, bonus, short in EMPLOYERS if rx.search(raw if short else key)), default=0)


def score(row: dict) -> int:
    title = row.get("title") or ""
    points = sum(w for rx, w in SCORE if rx.search(title))
    if PREFERRED and PREFERRED.search(str(row.get("location") or "")):
        points += PREFERRED_BONUS
    points += employer_bonus(row.get("company"))
    if tier(title) != "core":
        points -= 20
    return points


def area(row: dict) -> str:
    """corridor or remote; Instaffo index rows by their location."""
    if row.get("pass") == "index":
        loc = str(row.get("location") or "")
        return "corridor" if CORRIDOR.search(loc) and not re.search(r"remote|home.?office|deutschlandweit|bundesweit",
                                                                    loc, re.I) else "remote"
    return "corridor" if row.get("pass") == "corridor" else "remote"


def auto_read(row: dict) -> bool:
    """Read in full without asking. main() stores the decision as "auto" once the
    profile's cap (auto_read_max) is applied; before that, the score lines decide."""
    if "auto" in row:
        return bool(row["auto"])
    return row.get("tier") == "core" and row.get("score", 0) >= AUTO_READ[area(row)]


def cap_auto_read(rows: list[dict], cap: int) -> list[dict]:
    """Mark at most `cap` posting groups for the automatic read (0 = no cap):
    search-area roles first, then by score. Every reading costs the user's
    Claude quota, so the cap is what keeps a big day affordable; the rest stays
    in the title list."""
    eligible = [r for r in rows if not r.get("dup_of") and auto_read(r)]
    eligible.sort(key=lambda r: (area(r) != "corridor", -r.get("score", 0)))
    chosen = {r["url"] for r in (eligible[:cap] if cap else eligible)}
    return [{**r, "auto": r["url"] in chosen and not r.get("dup_of")} for r in rows]


def baseline(rows: list[dict], hours: dict[str, float], now: datetime) -> tuple[list[dict], list[dict]]:
    """First sweep without any history: only dated postings inside the window
    count as new. Undated ones (XING, Workwise) and a board index's old postings
    (Instaffo) would otherwise all look new at once; they are recorded, not read."""
    fresh, old = [], []
    for row in rows:
        window = hours.get(row["portal"].removesuffix("-search"))
        dated = bool(row.get("date")) and window is not None
        (fresh if dated and in_window(row["date"], now - timedelta(hours=window)) else old).append(row)
    return fresh, old


TITLE_NOISE = re.compile(
    r"\([^)]*\)|\[[^\]]*\]|\b[mwdfx]\s*[/|]\s*[mwdfx](\s*[/|]\s*[mwdfx])?\b|\ball genders?\b"
    r"|\s[-–|]\s.*$|\bin\s+[A-ZÄÖÜ][\wäöüß.-]+(\s+[\wäöüß.-]+){0,2}\s*$")


def group_key(row: dict) -> str:
    """Same employer, same role: one posting copied across cities or boards."""
    title = row.get("title") or ""
    for _ in range(2):  # a city sits before a " - Board.com" suffix: strip both
        title = TITLE_NOISE.sub(" ", title).strip()
    return seen_jobs.norm_company(row.get("company")) + "|" + seen_jobs.norm(title)


def collapse(rows: list[dict]) -> list[dict]:
    """Mark copies (dup_of = the first row's URL) and count them on the first.
    Rows must arrive in priority order; the first of a group represents it."""
    first: dict[str, dict] = {}
    out = []
    for row in rows:
        row = dict(row)
        key = group_key(row)
        if key in first and seen_jobs.norm_company(row.get("company")):
            lead = first[key]
            lead["copies"] = lead.get("copies", 1) + 1
            row["dup_of"] = lead["url"]
        else:
            first[key] = row
        out.append(row)
    return out


def title_list(rows: list[dict], tier_: str = "core") -> str:
    """One line per posting group of one tier, for reading every title: index
    into sweep_candidates.json, auto-read mark, score, area, portal, title,
    company, location, copies."""
    # "pts" is the title triage below, not /rank's 0-100 score.
    lines = ["# idx  read   pts area     portal     title | company | location | copies"]
    for i, r in enumerate(rows):
        if r.get("dup_of") or (r.get("tier") == "core") != (tier_ == "core"):
            continue
        copies = f" | x{r['copies']}" if r.get("copies", 1) > 1 else ""
        lines.append(f"{i:5}  {'AUTO' if auto_read(r) else ('edge' if r.get('tier') != 'core' else '    ')} "
                     f"{r.get('score', 0):5} {area(r):8} {r['portal'].removesuffix('-search')[:10]:10} "
                     f"{(r.get('title') or '')[:90]} | {(r.get('company') or '-')[:40]} | "
                     f"{str(r.get('location') or '-')[:30]}{copies}")
    return "\n".join(lines) + "\n"


def in_area(row: dict) -> bool:
    if row.get("pass") != "index":
        return True
    text = " ".join(str(row.get(k) or "") for k in ("location", "title", "remote_hint"))
    return bool(CORRIDOR.search(text))


# --- window ----------------------------------------------------------------


def load_state(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def window_hours(state: dict, portal: str, now: datetime, override: int | None = None) -> float:
    """Hours since the portal's last successful sweep, plus a 6-hour margin."""
    if override:
        return max(1, min(override, MAX_DAYS)) * 24.0
    last = (state.get("portals") or {}).get(portal, {}).get("last_success")
    if not last:
        return DEFAULT_DAYS * 24.0
    try:
        since = datetime.fromisoformat(last)
    except ValueError:
        return DEFAULT_DAYS * 24.0
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    hours = (now - since).total_seconds() / 3600 + 6
    return max(1.0, min(hours, MAX_DAYS * 24.0))


def window_days(state: dict, portal: str, now: datetime, override: int | None = None) -> int:
    """The window in whole days, for portals that filter by day."""
    return max(1, math.ceil(window_hours(state, portal, now, override) / 24))


def in_window(date: str | None, cutoff: datetime) -> bool:
    """Undated postings stay in: dedup, not the date, decides for them."""
    if not date:
        return True
    try:
        posted = datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError:
        return True
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    # Portals that give a bare date mean the whole day.
    if len(date) <= 10:
        posted += timedelta(days=1)
    return posted >= cutoff


# --- portal calls ----------------------------------------------------------


def run_cli(portal: str, args: list[str], timeout: int = 300) -> dict:
    """Run a portal CLI. stdout goes to a file, not a pipe, so large outputs
    arrive whole even on a CLI that still exits early."""
    cli = SKILLS / f"{portal}-search" / "cli" / "src" / "cli.ts"
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out:
        try:
            proc = subprocess.run(["bun", "run", str(cli), *args, "--format", "json"],
                                  stdout=out, stderr=subprocess.PIPE, text=True, timeout=timeout, cwd=ROOT)
        except subprocess.TimeoutExpired:
            return {"error": f"timeout after {timeout}s"}
        out.seek(0)
        text = out.read()
    if proc.returncode != 0:
        return {"error": (proc.stderr or text).strip()[-500:] or f"exit {proc.returncode}"}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {"error": f"unreadable JSON ({exc}): {text[:200]}"}


def is_rate_limit(error: str) -> bool:
    return bool(re.search(r"\b429\b|rate.?limit|too many requests", error, re.I))


def paginate(fetch, page_size: int, max_pages: int, delay: float = 0.0, sleep=time.sleep,
             stale_stop: bool = True) -> dict:
    """Page a search until the portal runs out.

    `fetch(page)` returns the CLI's JSON (or {"error": ...}). Stops on an empty
    page, on the portal's own total, or (with `stale_stop`) after two pages in
    a row that bring nothing new (LinkedIn repeats its last page instead of
    ending). XING reshuffles between requests, so a page without anything new
    there says nothing about the next one: it pages to the empty page. A page
    that fails is retried once (after a minute when rate-limited)."""
    results: dict[str, dict] = {}
    report = {"pages": 0, "results": 0, "total": None, "end": None, "error": None}
    stale = 0
    for page in range(1, max_pages + 1):
        data = fetch(page)
        if "error" in data:
            sleep(60 if is_rate_limit(data["error"]) else 10)
            data = fetch(page)
        if "error" in data:
            report["error"] = f"page {page}: {data['error']}"
            report["end"] = "error"
            break
        report["pages"] = page
        meta = data.get("meta") or {}
        if isinstance(meta.get("total"), int):
            report["total"] = meta["total"]
        rows = data.get("results") or []
        fresh = 0
        for row in rows:
            key = str(row.get("id") or row.get("url"))
            if key not in results:
                results[key] = row
                fresh += 1
        if not rows:
            report["end"] = "empty page"
            break
        if report["total"] is not None and page * page_size >= report["total"]:
            report["end"] = "portal total reached"
            break
        stale = stale + 1 if fresh == 0 else 0
        if stale_stop and stale >= 2:
            report["end"] = "no new results"
            break
        sleep(delay)
    else:
        report["end"] = "capped"
    report["results"] = len(results)
    if report["total"]:
        # Below 1.0 the portal served fewer distinct postings than it counted
        # (XING: unstable ordering and a 50-page ceiling).
        report["coverage"] = round(len(results) / report["total"], 2)
    return {"rows": list(results.values()), "report": report}


def window_args(plan: dict, hours: float) -> list[str]:
    """The portal-side filter. It may be wider than the window (`min_days`):
    where the portal's smallest bucket has unclear edges, a wider bucket plus
    the client-side date filter loses nothing. LinkedIn takes the exact
    window in minutes, which keeps its searches under the 1,000-result
    ceiling: a twice-daily run reads 10-20 hours, not a whole day."""
    mode = plan["window"]
    days = max(1, math.ceil(hours / 24))
    if mode == "minutes":
        return ["--jobage-minutes", str(math.ceil(hours * 60))]
    if mode == "jobage":
        return ["--jobage", str(max(days, plan.get("min_days", 1)))]
    return []


REMOTE_KEYS = ("workFromHome", "work_mode", "remoteWork", "homeoffice")


def normalize(portal: str, row: dict, pass_: str) -> dict:
    remote = next((row.get(k) for k in REMOTE_KEYS if row.get(k) not in (None, "")), None)
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "company": row.get("company"),
        "url": row.get("url"),
        "location": row.get("location"),
        "posted_date": (row.get("date") or None) and str(row["date"])[:10],
        "date": row.get("date"),
        "portal": f"{portal}-search",
        "source": "cli",
        "pass": pass_,
        "remote_hint": remote,
        # The band some portals show in their UI rather than the text (XING, Workwise,
        # freehire, Arbeitsagentur); tools/salary_band.py reads it before the text.
        "portal_salary": row.get("salary") or None,
    }


def sweep_index(portal: str, plan: dict, known) -> tuple[list[dict], list[dict]]:
    """Instaffo: list the board, hydrate only postings we have not seen."""
    data = run_cli(portal, ["index"])
    if "error" in data:
        return [], [{"pass": "index", "args": ["index"], "pages": 0, "results": 0, "total": None,
                     "end": "error", "error": data["error"]}]
    entries = data.get("results") or []
    unseen = [e for e in entries if not known(e)]
    wanted = [e for e in unseen if is_relevant(e.get("title"))]
    rows, errors = [], []
    for entry in wanted:
        detail = run_cli(portal, ["detail", entry["id"]])
        if "error" in detail:
            errors.append(f"{entry['id']}: {detail['error']}")
            continue
        rows.append(normalize(portal, detail, "index"))
        time.sleep(plan["delay"])
    # Unseen but irrelevant postings still get recorded, from the slug title.
    rows += [normalize(portal, e, "index") for e in unseen if not is_relevant(e.get("title"))]
    report = {"pass": "index", "args": ["index"], "pages": 1, "results": len(entries), "total": len(entries),
              "end": "complete index", "unseen": len(unseen), "hydrated": len(wanted) - len(errors),
              "error": "; ".join(errors[:5]) or None}
    return rows, [report]


# --- watchlist ---------------------------------------------------------------
#
# Employers whose roles appear only on their own career page: one fetch and one
# parser per page, checked once a week, not on every run. Empty by default; add
# an entry ("Name": (url, parser)) where a measured gap justifies it. A parser
# returns [{"title", "url", "location", "date"?}].

WATCHLIST_DAYS = 7
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def fetch(url: str, timeout: int = 40) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


WATCHLIST: dict = {}


def sweep_watchlist(state: dict, now: datetime, log) -> dict | None:
    """The watchlist as one more source, or None when it is empty or its week is not up."""
    if not WATCHLIST:
        return None
    last = (state.get("portals") or {}).get("watchlist", {}).get("last_success")
    if last and now - datetime.fromisoformat(last) < timedelta(days=WATCHLIST_DAYS):
        return None
    started = time.time()
    rows, reports = [], []
    for company, (url, parse) in WATCHLIST.items():
        try:
            found = parse(fetch(url))
            error = None if found else "no postings parsed: the page layout may have changed"
        except Exception as exc:  # noqa: BLE001 - any failure is reported verbatim
            found, error = [], f"{type(exc).__name__}: {exc}"
        rows += [{**normalize("watchlist", {**r, "company": company}, "corridor"),
                  "portal": "watchlist"} for r in found]
        reports.append({"pass": "corridor", "args": [company], "pages": 1, "results": len(found), "total": None,
                        "end": "error" if error else "complete index", "error": error, "kept": len(found)})
        log(f"watchlist: {company} -> {len(found)}" + (f" ({error})" if error else ""))
    failed = [r for r in reports if r["end"] == "error"]
    status = "ok" if not failed else ("broken" if len(failed) == len(reports) else "partial")
    return {"portal": "watchlist", "hours": WATCHLIST_DAYS * 24.0, "status": status, "capped": [],
            "searches": reports, "rows": rows, "seconds": round(time.time() - started)}


def sweep_portal(portal: str, hours: float, now: datetime, known, log) -> dict:
    plan = PLAN[portal]
    days = max(1, math.ceil(hours / 24))
    cutoff = now - timedelta(hours=hours)
    started = time.time()
    if plan.get("index"):
        rows, reports = sweep_index(portal, plan, known)
    else:
        rows, reports = [], []
        for search in plan["searches"]:
            args = ["search", *search["args"], *window_args(plan, hours)]
            res = paginate(lambda page: run_cli(portal, [*args, "--page", str(page)]),
                           plan["page_size"], plan["pages"], plan["delay"],
                           stale_stop=plan.get("stale_stop", True))
            kept = res["rows"]
            if search.get("keep") == "homeoffice":
                kept = [r for r in kept if r.get("homeoffice") is True]
            if plan["window"] != "none":
                kept = [r for r in kept if in_window(r.get("date"), cutoff)]
            rows += [normalize(portal, r, search["pass"]) for r in kept]
            reports.append({"pass": search["pass"], "args": search["args"], **res["report"], "kept": len(kept)})
            log(f"{portal}: {' '.join(search['args'])[:70]} -> {res['report']['results']} "
                f"({res['report']['pages']} pages, {res['report']['end']})")
    # "capped" is reported but is not a failure of the run: the window was read
    # as far as the portal allows, and widening it next time would only cap
    # harder. An error is a failure: the next window reaches back over it.
    failed = [r for r in reports if r.get("end") == "error"]
    status = "ok" if not failed else ("broken" if len(failed) == len(reports) else "partial")
    capped = [" ".join(r["args"]) for r in reports if r.get("end") == "capped"]
    return {"portal": portal, "hours": round(hours, 1), "status": status, "capped": capped,
            "searches": reports, "rows": rows,
            "seconds": round(time.time() - started)}


# --- main ------------------------------------------------------------------


def confirm(path: Path) -> int:
    """Promote each portal's pending sweep time to last_success."""
    state = load_state(path)
    done = []
    for portal, entry in (state.get("portals") or {}).items():
        pending = entry.pop("pending_success", None)
        if pending:
            entry["last_success"] = pending
            done.append(portal)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"confirmed: {', '.join(done) or 'nothing pending'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--confirm", action="store_true",
                    help="after the results are stored: make the last sweep's pending times count")
    ap.add_argument("--days", type=int, help="fixed window instead of the one from sweep_state.json")
    ap.add_argument("--portals", help="comma-separated subset, e.g. linkedin,xing")
    ap.add_argument("--state", type=Path, default=STATE)
    ap.add_argument("--seen", type=Path, default=seen_jobs.STATE)
    ap.add_argument("--tracker", type=Path, default=seen_jobs.TRACKER)
    ap.add_argument("--index", type=Path, default=seen_jobs.INDEX)
    ap.add_argument("--no-state", action="store_true", help="do not record this sweep in sweep_state.json")
    args = ap.parse_args()
    if args.confirm:
        return confirm(args.state)
    if not args.out:
        ap.error("--out is required unless --confirm is given")
    if not PROFILE_FILE.is_file():
        sys.exit(f"no search profile: copy {PROFILE_EXAMPLE.relative_to(ROOT)} to "
                 f"{PROFILE_FILE.relative_to(ROOT)} and adapt it (or let /setup write it)")

    portals = [p.strip() for p in args.portals.split(",")] if args.portals else list(PLAN)
    # The weekly watchlist runs with every full sweep, or alone with --portals watchlist.
    with_watchlist = not args.portals or "watchlist" in portals
    portals = [p for p in portals if p != "watchlist"]
    unknown = [p for p in portals if p not in PLAN]
    if unknown:
        sys.exit(f"unknown portal(s): {', '.join(unknown)}; known: {', '.join(PLAN)}")
    disabled = [p for p in portals if re.search(r"^enabled:\s*false\s*$",
                (SKILLS / f"{p}-search" / "SKILL.md").read_text(encoding="utf-8"), re.M)]
    portals = [p for p in portals if p not in disabled]

    now = datetime.now(timezone.utc)
    state = load_state(args.state)
    _, seen = seen_jobs.load_state(args.seen)
    known_urls = {seen_jobs.norm_url(e.get("url")) for e in seen.values() if isinstance(e, dict)} - {""}
    index_urls, _ = seen_jobs.index_sets(seen_jobs.load_index(args.index, now.date()))

    def known(entry: dict) -> bool:
        """Seen before, by URL: in seen_jobs.json or as an index fingerprint."""
        url = seen_jobs.norm_url(entry.get("url"))
        return url in known_urls or seen_jobs.fingerprints(entry)[0] in index_urls

    lock = threading.Lock()

    def log(msg: str) -> None:
        with lock:
            print(msg, file=sys.stderr, flush=True)

    # One thread per portal: portals run side by side, each portal's own
    # requests stay sequential and paced.
    with ThreadPoolExecutor(max_workers=len(portals) or 1) as pool:
        futures = {p: pool.submit(sweep_portal, p, window_hours(state, p, now, args.days), now, known, log)
                   for p in portals}
        results = {p: f.result() for p, f in futures.items()}
    if with_watchlist:
        weekly = sweep_watchlist(state, now, log)
        if weekly:
            results["watchlist"] = weekly

    pool_rows = [r for res in results.values() for r in res["rows"] if r.get("url") and r.get("title")]
    # Same posting from several searches or portals: keep the first.
    unique, urls = [], set()
    for row in pool_rows:
        key = seen_jobs.norm_url(row["url"])
        if key in urls:
            continue
        urls.add(key)
        unique.append(row)

    args.out.mkdir(parents=True, exist_ok=True)
    pool_file = args.out / "sweep_pool.json"
    pool_file.write_text(json.dumps(unique, ensure_ascii=False, indent=1), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(Path(seen_jobs.__file__)), "filter", "--in", str(pool_file),
                           "--state", str(args.seen), "--tracker", str(args.tracker),
                           "--index", str(args.index)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"seen_jobs filter failed: {proc.stderr.strip()}")
    filtered = json.loads(proc.stdout)
    new = filtered["new"]
    # No history at all: an empty seen_jobs.json (another tool may create it) counts as none.
    first_run = not known_urls and not index_urls
    baselined: list[dict] = []
    if first_run:
        new, baselined = baseline(new, {p: res["hours"] for p, res in results.items()}, now)
    wanted = [r for r in new if is_relevant(r["title"]) and in_area(r)]
    ranked = [{**r, "tier": tier(r["title"])} for r in wanted]
    ranked = [{**r, "score": score(r)} for r in ranked]
    ranked.sort(key=lambda r: (area(r) != "corridor", r["tier"] != "core", -r["score"]))
    candidates = cap_auto_read(collapse(ranked), int(PROFILE.get("auto_read_max") or 0))
    skipped = [{**{k: r.get(k) for k in ("title", "company", "url", "posted_date", "portal", "source")},
                "deadline": None, "fit": "low", "status": "skipped"}
               for r in [*new, *baselined] if r not in wanted]

    (args.out / "sweep_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "sweep_titles.txt").write_text(title_list(candidates), encoding="utf-8")
    # Edge titles passed only the wide filter (site managers, clerks, technicians):
    # a separate file, skimmed rather than weighed line by line.
    (args.out / "sweep_titles_edge.txt").write_text(title_list(candidates, "edge"), encoding="utf-8")
    (args.out / "sweep_skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "run": now.isoformat(timespec="seconds"),
        "portals": {p: {k: v for k, v in res.items() if k != "rows"} | {"kept": len(res["rows"])}
                    for p, res in results.items()},
        "skipped_disabled": disabled,
        "pool": len(unique), "dropped_as_seen": filtered["dropped"],
        "new": len(new), "candidates": len(candidates),
        "core": sum(1 for r in candidates if r["tier"] == "core"), "skipped": len(skipped),
        "groups": sum(1 for r in candidates if not r.get("dup_of")),
        "auto_read": sum(1 for r in candidates if not r.get("dup_of") and auto_read(r)),
        "auto_read_max": int(PROFILE.get("auto_read_max") or 0),
        "first_run_baselined": len(baselined),
        "long_window": [p for p, res in results.items() if res["hours"] > LONG_DAYS * 24],
    }
    (args.out / "sweep_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_state:
        portals_state = state.setdefault("portals", {})
        for p, res in results.items():
            entry = portals_state.setdefault(p, {})
            entry["last_run"] = now.isoformat(timespec="seconds")
            entry["last_status"] = res["status"]
            # A portal that failed keeps its old timestamp, so the next window
            # reaches back over the gap. A good one only becomes the new start
            # once --confirm says its results were stored.
            if res["status"] == "ok":
                entry["pending_success"] = now.isoformat(timespec="seconds")
        args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    long_window = [p for p, res in results.items() if res["hours"] > LONG_DAYS * 24]
    if long_window:
        print(f"long window (over {LONG_DAYS} days, slow and LinkedIn remote caps more): {', '.join(long_window)}")
    for p, res in results.items():
        print(f"{p:15} {res['status']:8} window {res['hours']}h  kept {len(res['rows']):5}  {res['seconds']}s"
              + (f"  capped: {len(res['capped'])}" if res["capped"] else ""))
    if baselined:
        print(f"first run: {len(baselined)} undated or older postings recorded as seen, not read")
    core = sum(1 for r in candidates if r["tier"] == "core")
    print(f"auto read: {report['auto_read']}" + (f" (capped at {report['auto_read_max']})" if report["auto_read_max"] else ""))
    print(f"pool {len(unique)}, new {len(new)}: {len(candidates)} candidates "
          f"({core} core, {len(candidates) - core} edge), {len(skipped)} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
