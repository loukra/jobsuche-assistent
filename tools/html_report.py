#!/usr/bin/env python3
"""Generate the application-tracker dashboard (`/html-report`).

Reads job_search_tracker.csv and documents/applications/*/outcome.md and writes
one self-contained HTML file: inline CSS, inline JS, hand-built inline SVG
charts, no external requests. Every value from the CSV or the outcome files is
HTML-escaped before it reaches the page.

    python tools/html_report.py                       # -> reports/application-dashboard.html
    python tools/html_report.py ~/Desktop/report.html # -> that path

Rules (mirroring .claude/commands/html-report.md):
- status buckets: drafted -> Drafted; applied -> Active; interview, offer, hired
  -> their own bucket; rejected / no_response / offer_declined / withdrawn (space
  spellings tolerated) -> Rejected/Closed; anything else -> Rejected/Closed and
  named once in the status breakdown.
- Drafted rows are excluded from every statistic except the status breakdown.
- Funnel stages come from history: current status OR ticked stage checkboxes
  in the matched outcome.md. Interview rounds = number of ticked interview
  checkboxes (Phone screen .. Final round), at least 1 once Interview is reached.
- Rejection rate = (rejected + no_response) / rows with a final outcome;
  offer_declined and withdrawn are resolved but not rejections.
- A 13-field row (written before `deadline` existed) is kept, deadline empty.
- Days quiet (open, sent rows only) count from the row's date or the latest
  dated note, whichever is more recent; 30+ days is flagged, status untouched.
  In the status breakdown and the Active card, quiet Active rows show as their
  own "Quiet 30+ days" slice (display only, the bucket stays Active).
- Application flow (Sankey): each stage splits into the next stage and the
  ways applications ended there (open, rejected, no response, declined,
  withdrawn, closed); stage reached uses the funnel rule.
"""

from __future__ import annotations

import argparse
import csv
import glob
import html
import math
import os
import re
import sys
from collections import Counter, OrderedDict
from datetime import date
from urllib.parse import urlparse

FIELDS = [
    "date", "company", "sector", "role", "role_type", "channel", "status",
    "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
    "source", "deadline",
]
STAGES = ["Phone screen", "Technical interview", "Case interview", "Final round", "Offer received"]
BUCKETS = ["Drafted", "Active", "Interview", "Offer", "Hired", "Rejected/Closed"]
COLORS = {
    "Drafted": "#64748b", "Active": "#3b82f6", "Interview": "#f59e0b",
    "Offer": "#8b5cf6", "Hired": "#22c55e", "Rejected/Closed": "#ef4444",
}
FUNNEL_COLORS = {"Applied": "#3b82f6", "Interview round 1": "#f59e0b", "Interview round 2": "#d97706", "Interview round 3+": "#b45309",
                 "Offer": "#8b5cf6", "Hired": "#22c55e"}
CLOSED = {"rejected", "no_response", "no response", "offer_declined", "offer declined", "withdrawn"}
TRUE_REJECTIONS = {"rejected", "no_response", "no response"}
WITHDRAWN = {"withdrawn", "offer_declined", "offer declined"}
FLOW_STAGES = ["Applied", "Round 1", "Round 2", "Round 3+", "Offer", "Hired"]
FLOW_ENDS = OrderedDict([  # status -> (end node label, colour), in vertical order within a column
    ("open", ("Open", "#94a3b8")), ("rejected", ("Rejected", "#ef4444")),
    ("no_response", ("No response", "#f87171")), ("offer_declined", ("Declined", "#a78bfa")),
    ("withdrawn", ("Withdrawn", "#64748b")), ("other", ("Closed", "#cbd5e1")),
])
NOTE_LIMIT = 80
QUIET_DAYS = 30
QUIET = f"Quiet {QUIET_DAYS}+ days"
COLORS[QUIET] = "#94a3b8"
DISPLAY_BUCKETS = BUCKETS[:2] + [QUIET] + BUCKETS[2:]
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


# ---------------------------------------------------------------- data

def read_tracker(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for rec in reader:
            if not any(rec):
                continue
            rec = list(rec) + [""] * (len(FIELDS) - len(rec))
            rows.append(dict(zip(FIELDS, rec[: len(FIELDS)])))
    return rows


def read_outcomes(root: str) -> list[dict]:
    outcomes = []
    for path in sorted(glob.glob(os.path.join(root, "documents", "applications", "*", "outcome.md"))):
        text = open(path, encoding="utf-8").read()
        title = re.search(r"^# Outcome:\s*(.+?)\s+[—–-]+\s+(.+)$", text, re.M)
        company, role = (title.group(1), title.group(2)) if title else (os.path.basename(os.path.dirname(path)), "")
        stages = {s: bool(re.search(r"- \[[xX]\]\s*" + re.escape(s), text)) for s in STAGES}
        outcomes.append({
            "company": company, "role": role, "stages": stages, "used": False,
            "dir": os.path.basename(os.path.dirname(path)),
        })
    return outcomes


def _matches(row: dict, outcome: dict) -> bool:
    rc, oc = norm(row["company"]), norm(outcome["company"])
    rr, orole = norm(row["role"]), norm(outcome["role"])
    company_ok = rc == oc or rc in oc or oc in rc
    role_ok = rr == orole or rr in orole or orole in rr or rr[:25] == orole[:25]
    return company_ok and role_ok


def merge_outcomes(rows: list[dict], outcomes: list[dict]) -> list[dict]:
    """Attach each outcome to its tracker row; return the outcomes left over."""
    for row in rows:
        row["outcome"] = None
        for outcome in outcomes:
            if not outcome["used"] and _matches(row, outcome):
                row["outcome"] = outcome
                outcome["used"] = True
                break
    return [o for o in outcomes if not o["used"]]


def bucket_of(status: str, unrecognised: set) -> str:
    s = (status or "").strip().lower()
    if s == "drafted":
        return "Drafted"
    if s == "applied":
        return "Active"
    if s in ("interview", "offer", "hired"):
        return s.capitalize()
    if s not in CLOSED:
        unrecognised.add(s or "(empty)")
    return "Rejected/Closed"


def reached(row: dict, stage: str) -> bool:
    bucket, outcome = row["bucket"], row["outcome"]
    status = (row["status"] or "").strip().lower()
    if stage == "Interview":
        return bucket in ("Interview", "Offer", "Hired") or bool(
            outcome and any(outcome["stages"][s] for s in STAGES[:4]))
    if stage == "Offer":
        return bucket in ("Offer", "Hired") or status in ("offer_declined", "offer declined") or bool(
            outcome and outcome["stages"]["Offer received"])
    if stage == "Hired":
        return bucket == "Hired"
    return True


def interview_rounds(row: dict) -> tuple[int, str]:
    """Interview rounds reached and the furthest ticked stage name ("" if none ticked)."""
    outcome = row["outcome"]
    ticked = [s for s in STAGES[:4] if outcome and outcome["stages"][s]]
    rounds = len(ticked) or (1 if reached(row, "Interview") else 0)
    return rounds, (ticked[-1] if ticked else "")


def days_quiet(row: dict, today: str) -> int | None:
    """Days since the last contact for an open, sent row; None for drafted or closed rows."""
    if row["bucket"] not in ("Active", "Interview", "Offer"):
        return None
    dates = []
    for y, m, d in DATE_RE.findall(row["date"] + " " + row["notes"]):
        try:
            dates.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    if not dates:
        return None
    return max(0, (date.fromisoformat(today) - max(dates)).days)


def period_of(value: str) -> str:
    value = (value or "").strip()
    if re.match(r"\d{4}-\d{2}", value):
        return value[:7]
    if re.match(r"\d{4}", value):
        return value[:4]
    return "(unknown)"


# Sector groups for the chart and the filter, in match order: the specific groups
# come first so that "Healthcare software" lands in Healthcare, not in the
# software catch-all. Keywords of four characters or fewer match on word
# boundaries only ("hr" must not fire on "Fahrzeug"); longer ones match as
# substrings ("health" covers "eHealth"). Writers of the tracker put the group
# first: "Healthcare: lokale KI für Arztpraxen" (see /apply Step 6b), and the
# prefix wins over any keyword. Rows that still end up in "Other" are listed in
# the script summary so the tracker can be fixed.
SECTOR_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Defence & Space", ("defence", "defense", "space", "aerospace", "raumfahrt", "military", "militär",
                         "rüstung", "sonar", "naval", "maritime", "schiffbau", "shipbuilding", "satellit")),
    ("Healthcare", ("health", "medizin", "medical", "medtech", "arztprax", "praxis", "patient", "klinik",
                    "clinic", "hospital", "pharma", "pflege", "dental", "care")),
    ("Research & Deep Tech", ("quantum", "research", "forschung", "institut", "fraunhofer", "dfki", "offis",
                              "universit", "hochschule", "laborator", "deep tech")),
    ("AI & Data Products", ("künstliche intelligenz", "machine learning", "maschinelles lernen", "data science",
                            "analytics", "computer vision", "robotic", "llm", "nlp", "ai", "ki")),
    ("Energy, Industry & Measurement", ("energy", "energie", "utility", "versorger", "messtechnik", "measurement",
                                        "industrial", "industrie", "automation", "automatisierung", "maschinenbau",
                                        "manufacturing", "fertigung", "sensor", "acoustic", "akustik", "audio",
                                        "signal", "photonic", "optics", "engineering", "dsp")),
    ("Mobility & Automotive", ("carsharing", "mobilität", "mobility", "automotive", "fahrzeug", "automobil",
                               "vehicle", "logistik", "logistics", "verkehr", "transport", "aviation", "luftfahrt",
                               "airline", "bahn")),
    ("Finance, Real Estate & Commerce", ("bank", "finanz", "financ", "insurance", "versicherung", "fintech",
                                         "immobilien", "proptech", "real estate", "wohnungs", "handel", "commerce",
                                         "onlineshop", "online-shop", "webshop", "retail", "payment", "zahlung",
                                         "shop")),
    ("Media & Publishing", ("verlag", "media", "publishing", "zeitung", "journalis", "broadcast", "rundfunk",
                            "marketing", "agentur", "werbung")),
    ("Public Sector & Education", ("öffentlich", "public sector", "behörde", "kommunal", "verwaltung", "government",
                                   "education", "bildung", "schule", "e-learning", "lernplattform")),
    ("Business Software & IT", ("saas", "software", "e-mail", "email", "outlook", "monitoring", "enterprise",
                                "it-services", "it services", "it-dienstleist", "systemhaus", "payroll", "cloud",
                                "plattform", "platform", "telekommunikation", "telco", "hosting", "rechenzentrum",
                                "security", "hr", "erp", "crm", "it")),
]

# Short names a tracker writer may put before the colon, all resolving to a group.
SECTOR_ALIASES: dict[str, str] = {
    "defence": "Defence & Space", "defense": "Defence & Space", "space": "Defence & Space",
    "aerospace": "Defence & Space", "maritime": "Defence & Space",
    "healthcare": "Healthcare", "health": "Healthcare", "ehealth": "Healthcare", "medtech": "Healthcare",
    "medizin": "Healthcare",
    "research": "Research & Deep Tech", "deep tech": "Research & Deep Tech", "forschung": "Research & Deep Tech",
    "ai": "AI & Data Products", "ki": "AI & Data Products", "ai & data": "AI & Data Products",
    "data": "AI & Data Products", "ml": "AI & Data Products",
    "energy": "Energy, Industry & Measurement", "industry": "Energy, Industry & Measurement",
    "industrie": "Energy, Industry & Measurement", "measurement": "Energy, Industry & Measurement",
    "messtechnik": "Energy, Industry & Measurement", "engineering": "Energy, Industry & Measurement",
    "mobility": "Mobility & Automotive", "automotive": "Mobility & Automotive",
    "logistics": "Mobility & Automotive", "logistik": "Mobility & Automotive", "transport": "Mobility & Automotive",
    "finance": "Finance, Real Estate & Commerce", "finanz": "Finance, Real Estate & Commerce",
    "fintech": "Finance, Real Estate & Commerce", "insurance": "Finance, Real Estate & Commerce",
    "real estate": "Finance, Real Estate & Commerce", "immobilien": "Finance, Real Estate & Commerce",
    "commerce": "Finance, Real Estate & Commerce", "retail": "Finance, Real Estate & Commerce",
    "handel": "Finance, Real Estate & Commerce",
    "media": "Media & Publishing", "publishing": "Media & Publishing", "verlag": "Media & Publishing",
    "marketing": "Media & Publishing",
    "public sector": "Public Sector & Education", "public": "Public Sector & Education",
    "education": "Public Sector & Education", "bildung": "Public Sector & Education",
    "verwaltung": "Public Sector & Education",
    "software": "Business Software & IT", "business software": "Business Software & IT",
    "it": "Business Software & IT", "saas": "Business Software & IT", "it services": "Business Software & IT",
    "other": "Other", "sonstige": "Other",
}
for _group, _ in SECTOR_GROUPS:
    SECTOR_ALIASES[_group.lower()] = _group
SECTOR_GROUP_NAMES: list[str] = [g for g, _ in SECTOR_GROUPS] + ["Other"]


def _alias_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace(" and ", " & ").replace(" und ", " & "))


def _keyword_hit(keyword: str, text: str) -> bool:
    if len(keyword) <= 4:
        return re.search(r"(?<![\w])" + re.escape(keyword) + r"(?![\w])", text) is not None
    return keyword in text


def sector_group(sector: str) -> str:
    """Collapse the free-text tracker sector into one coarse chart bucket.

    Resolution order: (1) an explicit group before the first colon
    ("Healthcare: lokale KI für Arztpraxen") or a bare group/alias name;
    (2) the first SECTOR_GROUPS entry with a keyword hit; (3) "Other".
    An empty sector is "(not recorded)".
    """
    text = (sector or "").strip()
    if not text:
        return "(not recorded)"
    head = text.split(":", 1)[0] if ":" in text and len(text.split(":", 1)[0]) <= 40 else text
    alias = SECTOR_ALIASES.get(_alias_key(head))
    if alias:
        return alias
    low = text.lower()
    for group, keywords in SECTOR_GROUPS:
        if any(_keyword_hit(k, low) for k in keywords):
            return group
    return "Other"


# Channel labels for the chart: the tracker's `channel` column only says
# "portal" / "online" / "referral", so the actual board is read off the
# `source` URL's host. Applicant-tracking hosts count as the company's own site.
JOB_BOARDS: dict[str, str] = {
    "linkedin.com": "LinkedIn", "xing.com": "XING", "stepstone.de": "StepStone", "stepstone.com": "StepStone",
    "join.com": "JOIN", "indeed.com": "Indeed", "indeed.de": "Indeed", "arbeitnow.com": "Arbeitnow",
    "freehire.me": "freehire", "instaffo.com": "Instaffo", "arbeitsagentur.de": "Arbeitsagentur",
    "glassdoor.com": "Glassdoor", "glassdoor.de": "Glassdoor", "kununu.com": "kununu", "monster.de": "Monster",
    "jobvector.de": "jobvector", "honeypot.io": "Honeypot", "get-in-it.de": "get in IT", "germantechjobs.de": "GermanTechJobs",
}
ATS_HOSTS: tuple[str, ...] = ("myworkdayjobs.com", "workday.com", "softgarden.io", "greenhouse.io", "lever.co",
                              "personio.de", "personio.com", "smartrecruiters.com", "ashbyhq.com", "workable.com",
                              "flair.hr", "recruitee.com", "onlyfy.jobs", "jobs.personio", "teamtailor.com")
CHANNEL_NAMES: dict[str, str] = {
    "linkedin": "LinkedIn", "xing": "XING", "stepstone": "StepStone", "join": "JOIN", "indeed": "Indeed",
    "arbeitnow": "Arbeitnow", "freehire": "freehire", "instaffo": "Instaffo", "referral": "Referral",
    "empfehlung": "Referral", "email": "E-mail", "e-mail": "E-mail", "mail": "E-mail",
    "company site": "Company site", "careers page": "Company site",
}
GENERIC_CHANNELS: tuple[str, ...] = ("portal", "online", "other", "web", "")


def _host(url: str) -> str:
    host = urlparse(url.strip()).netloc.lower() if url and url.strip().lower().startswith("http") else ""
    return host.split("@")[-1].split(":")[0]


def channel_label(row: dict) -> str:
    """Name the board or site an application came through.

    A channel value that names a platform ("instaffo", "referral") wins. The
    generic values the commands write ("portal", "online") are refined by the
    `source` host: a known job board by name, an applicant-tracking host or any
    other company domain as "Company site" when the channel is "online", and
    the bare domain otherwise. Without a usable source the raw channel is shown.
    """
    raw = (row.get("channel") or "").strip().lower()
    if raw in CHANNEL_NAMES:
        return CHANNEL_NAMES[raw]
    if raw not in GENERIC_CHANNELS:
        return raw.capitalize()
    host = _host(row.get("source") or "")
    if host:
        for domain, name in JOB_BOARDS.items():
            if host == domain or host.endswith("." + domain):
                return name
        if any(host == a or host.endswith("." + a) for a in ATS_HOSTS) or raw == "online":
            return "Company site"
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    return (raw or "other").capitalize()


def flow_path(row: dict) -> tuple[list[str], str | None]:
    """Stages one sent row passed through and how it ended there (None once hired)."""
    rounds = interview_rounds(row)[0]
    path = ["Applied"] + [f"Round {n}" for n in (1, 2) if rounds >= n] + (["Round 3+"] if rounds >= 3 else [])
    if reached(row, "Offer"):
        path.append("Offer")
    if reached(row, "Hired"):
        return path + ["Hired"], None
    status = (row["status"] or "").strip().lower().replace(" ", "_")
    if row["bucket"] in ("Active", "Interview", "Offer"):
        return path, "open"
    return path, status if status in FLOW_ENDS else "other"


def end_label(stage: str, kind: str, label: str) -> str:
    """Name an end node by the stage it left, so two "Rejected" nodes never read alike."""
    if stage == "Applied":
        return {"open": "Waiting for reply", "rejected": "Rejected at screening"}.get(kind, label)
    if stage == "Offer" and kind in ("open", "offer_declined"):
        return "Offer pending" if kind == "open" else "Offer declined"
    if kind == "open":
        return f"Open in {stage.lower()}"
    return f"{label} after {stage.lower()}"


def application_flow(sent: list[dict]) -> dict:
    """Sankey nodes and links: each stage splits into the next stage and the ways applications ended there."""
    paths = [flow_path(r) for r in sent]
    present = [s for s in FLOW_STAGES if any(s in p for p, _ in paths)]
    col = {s: i for i, s in enumerate(present)}
    counts: Counter = Counter()
    links: Counter = Counter()
    for path, end in paths:
        for a, b in zip(path, path[1:]):
            links[(a, b)] += 1
        for s in path:
            counts[s] += 1
        if end:
            node = f"{path[-1]}|{end}"
            counts[node] += 1
            links[(path[-1], node)] += 1
    nodes = []
    for s in present:
        nodes.append({"id": s, "label": s, "col": col[s], "count": counts[s],
                      "color": FUNNEL_COLORS[s.replace("Round", "Interview round")],
                      "title": f"{s}: {counts[s]}"})
        for kind, (label, color) in FLOW_ENDS.items():
            node = f"{s}|{kind}"
            if counts[node]:
                text = end_label(s, kind, label)
                nodes.append({"id": node, "label": text, "col": col[s] + 1, "count": counts[node],
                              "color": color, "title": f"{text}: {counts[node]}"})
    return {"nodes": nodes, "links": [(a, b, n) for (a, b), n in links.items()]}


def compute_stats(rows: list[dict], today: str) -> dict:
    unrecognised: set = set()
    for row in rows:
        row["bucket"] = bucket_of(row["status"], unrecognised)
        row["quiet"] = days_quiet(row, today)
    sent = [r for r in rows if r["bucket"] != "Drafted"]
    rounds = [interview_rounds(r)[0] for r in sent]
    funnel = OrderedDict([
        ("Applied", len(sent)),
        ("Interview round 1", sum(1 for n in rounds if n >= 1)),
        ("Interview round 2", sum(1 for n in rounds if n >= 2)),
        ("Interview round 3+", sum(1 for n in rounds if n >= 3)),
        ("Offer", sum(1 for r in sent if reached(r, "Offer"))),
        ("Hired", sum(1 for r in sent if reached(r, "Hired"))),
    ])
    statuses = [(r["status"] or "").strip().lower() for r in sent]
    true_rejections = sum(1 for s in statuses if s in TRUE_REJECTIONS)
    resolved = sum(1 for s, r in zip(statuses, sent) if s in CLOSED or r["bucket"] == "Hired")
    withdrawn = sum(1 for s in statuses if s in WITHDRAWN)
    return {
        "sent": len(sent),
        "drafted": sum(1 for r in rows if r["bucket"] == "Drafted"),
        "by_bucket": Counter(r["bucket"] for r in rows),
        "display_buckets": Counter(
            QUIET if r["bucket"] == "Active" and (r["quiet"] or 0) >= QUIET_DAYS else r["bucket"] for r in rows),
        "by_sector": Counter(sector_group(r["sector"]) for r in sent),
        "other_sectors": [f'{r["company"].strip()}: {r["sector"].strip()}' for r in sent
                          if sector_group(r["sector"]) == "Other"],
        "unrecorded_sectors": [r["company"].strip() for r in sent if not r["sector"].strip()],
        "by_channel": Counter(channel_label(r) for r in sent),
        "by_period": Counter(period_of(r["date"]) for r in sent),
        "funnel": funnel,
        "flow": application_flow(sent),
        "quiet": sorted((r["company"].strip() for r in sent if (r["quiet"] or 0) >= QUIET_DAYS), key=str.lower),
        "past_screen_pct": round(100 * funnel["Interview round 1"] / len(sent)) if sent else 0,
        "true_rejections": true_rejections,
        "resolved": resolved,
        "withdrawn": withdrawn,
        "rejection_rate": round(100 * true_rejections / resolved) if resolved else None,
        "unrecognised": sorted(unrecognised),
    }


# ---------------------------------------------------------------- charts

def doughnut(counts: Counter) -> str:
    items = [(b, counts[b]) for b in DISPLAY_BUCKETS if counts.get(b)]
    total = sum(n for _, n in items)
    label = "Status breakdown: " + (", ".join(f"{n} {b}" for b, n in items) or "no data")
    if not total:
        return (f'<svg role="img" aria-label="{esc(label)}" viewBox="0 0 340 180" class="chart">'
                f'<text x="170" y="95" text-anchor="middle" class="muted">No data</text></svg>')
    cx = cy = 90
    outer, inner = 80, 50
    parts = []
    angle = -math.pi / 2
    for b, n in items:
        frac = n / total
        end = angle + 2 * math.pi * frac
        if len(items) == 1:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{(outer + inner) / 2}" fill="none" '
                         f'stroke="{COLORS[b]}" stroke-width="{outer - inner}"><title>{esc(b)}: {n}</title></circle>')
        else:
            large = 1 if frac > 0.5 else 0
            x1, y1 = cx + outer * math.cos(angle), cy + outer * math.sin(angle)
            x2, y2 = cx + outer * math.cos(end), cy + outer * math.sin(end)
            x3, y3 = cx + inner * math.cos(end), cy + inner * math.sin(end)
            x4, y4 = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
            d = (f"M{x1:.2f},{y1:.2f} A{outer},{outer} 0 {large} 1 {x2:.2f},{y2:.2f} "
                 f"L{x3:.2f},{y3:.2f} A{inner},{inner} 0 {large} 0 {x4:.2f},{y4:.2f} Z")
            parts.append(f'<path d="{d}" fill="{COLORS[b]}"><title>{esc(b)}: {n}</title></path>')
        angle = end
    parts.append(f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" font-size="24" '
                 f'font-weight="700" fill="var(--text)">{total}</text>')
    y = 40
    for b, n in items:
        parts.append(f'<rect x="200" y="{y - 10}" width="12" height="12" rx="2" fill="{COLORS[b]}"/>'
                     f'<text x="218" y="{y}" font-size="12" fill="var(--text)">{esc(b)} ({n})</text>')
        y += 22
    return f'<svg role="img" aria-label="{esc(label)}" viewBox="0 0 340 180" class="chart">' + "".join(parts) + "</svg>"


def hbars(items: list[tuple[str, int]], title: str, color: str = "#3b82f6",
          colors: dict | None = None, label_width: int = 150) -> str:
    if not items:
        return (f'<svg role="img" aria-label="{esc(title)}: no data" viewBox="0 0 460 60" class="chart">'
                f'<text x="230" y="35" text-anchor="middle" class="muted">No data</text></svg>')
    biggest = max(v for _, v in items) or 1
    row_h, width = 28, 460
    bar_x = label_width + 8
    bar_w = width - bar_x - 40
    height = row_h * len(items) + 10
    label = title + ": " + ", ".join(f"{k} {v}" for k, v in items)
    parts = []
    for i, (key, value) in enumerate(items):
        y = 5 + i * row_h
        w = bar_w * value / biggest
        c = (colors or {}).get(key, color)
        shown = key if len(key) <= 26 else key[:25] + "…"
        parts.append(f'<text x="{label_width}" y="{y + 17}" text-anchor="end" font-size="12" '
                     f'fill="var(--text)"><title>{esc(key)}</title>{esc(shown)}</text>')
        parts.append(f'<rect x="{bar_x}" y="{y + 4}" width="{w:.1f}" height="18" rx="3" fill="{c}">'
                     f'<title>{esc(key)}: {value}</title></rect>')
        parts.append(f'<text x="{bar_x + w + 6:.1f}" y="{y + 17}" font-size="12" font-weight="600" '
                     f'fill="var(--text)">{value}</text>')
    return f'<svg role="img" aria-label="{esc(label)}" viewBox="0 0 {width} {height}" class="chart">' + "".join(parts) + "</svg>"


def sankey(flow: dict) -> str:
    """Hand-built Sankey: node height and band width proportional to the number of applications."""
    nodes, links = flow["nodes"], flow["links"]
    if not nodes or not nodes[0]["count"]:
        return ('<svg role="img" aria-label="Application flow: no data" viewBox="0 0 920 60" class="chart">'
                '<text x="460" y="35" text-anchor="middle" class="muted">No data</text></svg>')
    width, height, node_w, gap, label_w, top = 920, 300, 14, 14, 200, 10
    columns: dict[int, list[dict]] = {}
    for n in nodes:
        columns.setdefault(n["col"], []).append(n)
    n_cols = max(columns) + 1
    scale = min((height - gap * (len(c) - 1)) / sum(n["count"] for n in c) for c in columns.values())
    step = (width - label_w - node_w) / max(n_cols - 1, 1)
    for i, column in columns.items():
        column.sort(key=lambda n: "|" in n["id"])  # the stage that continues on top, its end nodes below
        y = top
        for n in column:
            n["x"], n["y"], n["h"] = i * step, y, n["count"] * scale
            y += n["h"] + gap
    by_id = {n["id"]: n for n in nodes}
    out_y = {n["id"]: n["y"] for n in nodes}
    in_y = {n["id"]: n["y"] for n in nodes}
    parts = []
    for a, b, value in sorted(links, key=lambda l: (by_id[l[0]]["y"], by_id[l[1]]["y"])):
        src, dst, thick = by_id[a], by_id[b], value * scale
        x0, x1 = src["x"] + node_w, dst["x"]
        y0, y1 = out_y[a], in_y[b]
        out_y[a] += thick
        in_y[b] += thick
        xm = (x0 + x1) / 2
        d = (f"M{x0:.1f},{y0:.1f} C{xm:.1f},{y0:.1f} {xm:.1f},{y1:.1f} {x1:.1f},{y1:.1f} "
             f"L{x1:.1f},{y1 + thick:.1f} C{xm:.1f},{y1 + thick:.1f} {xm:.1f},{y0 + thick:.1f} {x0:.1f},{y0 + thick:.1f} Z")
        parts.append(f'<path d="{d}" fill="{dst["color"]}" fill-opacity="0.35">'
                     f'<title>{esc(src["label"])} → {esc(dst["title"])}</title></path>')
    for n in nodes:
        parts.append(f'<rect x="{n["x"]:.1f}" y="{n["y"]:.1f}" width="{node_w}" height="{max(n["h"], 1):.1f}" '
                     f'fill="{n["color"]}"><title>{esc(n["title"])}</title></rect>')
        parts.append(f'<text x="{n["x"] + node_w + 6:.1f}" y="{n["y"] + n["h"] / 2 + 5:.1f}" font-size="14" '
                     f'fill="var(--text)" stroke="var(--card)" stroke-width="3" paint-order="stroke">'
                     f'<tspan font-weight="600">{esc(n["label"])}</tspan> ({n["count"]})</text>')
    label = "Application flow: " + ", ".join(f'{n["title"]}' for n in nodes)
    return (f'<svg role="img" aria-label="{esc(label)}" viewBox="0 0 {width} {height + 2 * top}" class="chart">'
            + "".join(parts) + "</svg>")


# ---------------------------------------------------------------- page

CSS = """
:root{--bg:#f1f5f9;--card:#fff;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;--drafted:#64748b;--active:#3b82f6;--interview:#f59e0b;--offer:#8b5cf6;--hired:#22c55e;--closed:#ef4444}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.45}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px}
header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:20px}header h1{margin:0;font-size:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:14px 16px;border-left:5px solid var(--c)}
.card .num{font-size:32px;font-weight:700;line-height:1}.card .lbl{color:var(--muted);margin-top:6px;font-size:13px}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}.chart-card.wide{grid-column:1/-1}@media(max-width:900px){.charts{grid-template-columns:1fr}}
.chart-card{background:var(--card);border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:16px}.chart-card h3{margin:0 0 10px;font-size:15px}
.chart{width:100%;height:auto;display:block}.muted{color:var(--muted)}.small{font-size:12px}
.kpis{display:flex;gap:24px;flex-wrap:wrap;margin:0 0 20px;padding:12px 16px;background:var(--card);border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08)}.kpis div span{display:block;color:var(--muted);font-size:12px}
.tablecard{background:var(--card);border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:16px;overflow-x:auto}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.toolbar h2{margin:0 auto 0 0;font-size:18px}
.toolbar select,.toolbar input{padding:6px 10px;border:1px solid var(--border);border-radius:6px;font:inherit;background:#fff}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;vertical-align:top;border-bottom:1px solid var(--border)}
th{font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);background:#f8fafc;position:sticky;top:0}
tbody tr:nth-child(even){background:#f8fafc}td.nowrap{white-space:nowrap}td.notes{max-width:320px;color:#334155}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;color:#fff;background:var(--c);white-space:nowrap}.raw{font-size:11px;color:var(--muted);margin-top:2px}
td.quiet{color:#b45309;font-weight:700}.archive{cursor:help;font-size:12px}a{color:var(--active)}#count{color:var(--muted);font-size:12px}
footer{text-align:center;color:var(--muted);font-size:12px;margin-top:24px}
"""

JS = """
(function(){
var s=document.getElementById('fStatus'),c=document.getElementById('fSector'),t=document.getElementById('fText'),rows=document.querySelectorAll('tbody tr'),cnt=document.getElementById('count');
function norm(x){return x.toLowerCase().replace(/[^a-z0-9äöüß]+/g,' ').trim();}
function apply(){var q=norm(t.value),n=0;rows.forEach(function(r){var ok=(!s.value||r.dataset.status===s.value)&&(!c.value||r.dataset.sector===c.value)&&(!q||r.dataset.search.indexOf(q)>=0);r.style.display=ok?'':'none';if(ok)n++;});cnt.textContent=n+' of '+rows.length+' shown';}
[s,c,t].forEach(function(e){e.addEventListener('input',apply);e.addEventListener('change',apply);});apply();
})();
"""


def cell(value: str) -> str:
    return esc(value.strip()) if value and value.strip() else "—"


def table_rows(rows: list[dict], show_deadline: bool) -> str:
    ordered = sorted(rows, key=lambda r: r["company"].lower())
    ordered = sorted(ordered, key=lambda r: r["date"].strip(), reverse=True)
    out = []
    for r in ordered:
        notes = r["notes"].strip()
        short = notes if len(notes) <= NOTE_LIMIT else notes[: NOTE_LIMIT - 1] + "…"
        src = r["source"].strip()
        src_cell = (f'<a href="{esc(src)}" target="_blank" rel="noopener">link ↗</a>'
                    if src.startswith("http") else cell(src))
        archive = ""
        if r["outcome"]:
            ticked = [s for s in STAGES if r["outcome"]["stages"][s]]
            archive = (f' <span class="archive" title="Archive: {esc(r["outcome"]["dir"])}; stages reached: '
                       f'{esc(", ".join(ticked) if ticked else "none")}">📁</span>')
        sector = sector_group(r["sector"])
        detail = r["sector"].strip()
        sector_cell = (f'{esc(sector)}<div class="raw" title="{esc(detail)}">{esc(detail)}</div>'
                       if detail and detail != sector else cell(sector))
        quiet = r["quiet"]
        quiet_cell = ("<td>—</td>" if quiet is None else
                      f'<td class="nowrap{" quiet" if quiet >= QUIET_DAYS else ""}">{quiet} d</td>')
        n_rounds, furthest = interview_rounds(r)
        round_note = (f' · round {n_rounds}' + (f': {esc(furthest)}' if furthest else "")) if n_rounds else ""
        channel = channel_label(r)
        raw_channel = r["channel"].strip()
        channel_cell = (f'{esc(channel)}<div class="raw">{esc(raw_channel)}</div>'
                        if raw_channel and raw_channel.lower() != channel.lower() else cell(channel))
        out.append(
            f'<tr data-status="{esc(r["bucket"])}" data-sector="{esc(sector)}" '
            f'data-search="{esc(norm(r["company"] + " " + r["role"] + " " + r["sector"]))}">'
            f'<td class="nowrap">{cell(r["date"])}</td>'
            + (f'<td class="nowrap">{cell(r["deadline"])}</td>' if show_deadline else "")
            + f'<td><strong>{cell(r["company"])}</strong>{archive}</td><td>{cell(r["role"])}</td>'
            f'<td>{sector_cell}</td><td>{channel_cell}</td>'
            f'<td><span class="pill" style="--c:{COLORS[r["bucket"]]}">{esc(r["bucket"])}</span>'
            f'<div class="raw">{esc(r["status"].strip().lower())}{round_note}</div></td>'
            f'{quiet_cell}<td class="notes" title="{esc(notes)}">{cell(short)}</td><td>{src_cell}</td></tr>')
    return "".join(out)


def render(rows: list[dict], stats: dict, unmatched: list[dict], today: str) -> str:
    sector_items = sorted(stats["by_sector"].items(), key=lambda kv: (-kv[1], kv[0].lower()))
    channel_items = sorted(stats["by_channel"].items(), key=lambda kv: (-kv[1], kv[0]))
    period_text = " · ".join(f"{p}: {n}" for p, n in sorted(stats["by_period"].items())) or "—"
    if stats["rejection_rate"] is None:
        rejection_text = "n/a · nothing resolved yet"
    else:
        rejection_text = f'{stats["rejection_rate"]}% · {stats["true_rejections"]} of {stats["resolved"]} resolved'
        if stats["withdrawn"]:
            rejection_text += f', {stats["withdrawn"]} withdrawn'
    by_bucket, shown = stats["by_bucket"], stats["display_buckets"]
    drafted_card = [("Drafted", stats["drafted"], COLORS["Drafted"])] if stats["drafted"] else []
    cards = [("Sent", stats["sent"], "#0f172a")] + drafted_card + [
        (b, shown[b], COLORS[b]) for b in BUCKETS[1:]] + [(QUIET, len(stats["quiet"]), COLORS[QUIET])]
    cards_html = "".join(f'<div class="card" style="--c:{c}"><div class="num">{n}</div>'
                         f'<div class="lbl">{esc(l)}</div></div>' for l, n, c in cards)
    status_opts = "".join(f'<option value="{b}">{b}</option>' for b in BUCKETS if by_bucket.get(b))
    sector_opts = "".join(f'<option value="{esc(s)}">{esc(s)}</option>'
                          for s, _ in sorted(stats["by_sector"].items(), key=lambda kv: kv[0].lower()))
    unrecognised_note = (f'<p class="muted small">Unrecognised status value(s) grouped under Rejected/Closed: '
                         f'{esc(", ".join(stats["unrecognised"]))}</p>' if stats["unrecognised"] else "")
    unmatched_note = ('<p class="muted small">Archived outcome files without a tracker match: '
                      + esc("; ".join(f'{o["company"]} — {o["role"]}' for o in unmatched)) + "</p>"
                      if unmatched else "")
    show_deadline = any(r["deadline"].strip() for r in rows)
    deadline_th = "<th>Deadline</th>" if show_deadline else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Dashboard</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>🔍 Job Search Dashboard</h1><div class="muted">Generated: {today}</div></header>
<div class="cards">{cards_html}</div>
<div class="kpis">
<div><span>Past resume screen</span><strong>{stats["past_screen_pct"]}%</strong> ({stats["funnel"]["Interview round 1"]} of {stats["sent"]} reached an interview or beyond)</div>
<div><span>Rejection rate</span><strong>{esc(rejection_text)}</strong></div>
<div><span>By period</span>{esc(period_text)}</div>
</div>
<div class="charts">
<div class="chart-card"><h3>Status breakdown</h3>{doughnut(shown)}{unrecognised_note}</div>
<div class="chart-card"><h3>By sector</h3>{hbars(sector_items, "Applications by sector", color="#0ea5e9", label_width=190)}</div>
<div class="chart-card"><h3>By channel</h3>{hbars(channel_items, "Applications by channel", color="#14b8a6", label_width=110)}</div>
<div class="chart-card"><h3>Application funnel</h3>{hbars(list(stats["funnel"].items()), "Application funnel", colors=FUNNEL_COLORS, label_width=130)}<p class="muted small">Stage reached = current status or ticked stage in the archived outcome file. Interview round N = at least N ticked interview stages (round 1 also once the status says interview).</p></div>
<div class="chart-card wide"><h3>Application flow</h3>{sankey(stats["flow"])}<p class="muted small">Each stage splits into the next stage and the applications that ended there: still open, rejected, no response, withdrawn or declined. Same stage rule as the funnel.</p></div>
</div>
<div class="tablecard">
<div class="toolbar"><h2>Applications</h2><span id="count"></span>
<select id="fStatus"><option value="">All statuses</option>{status_opts}</select>
<select id="fSector"><option value="">All sectors</option>{sector_opts}</select>
<input id="fText" type="search" placeholder="🔍 company, role, sector"></div>
<table><thead><tr><th>Date</th>{deadline_th}<th>Company</th><th>Role</th><th>Sector</th><th>Channel</th><th>Status</th><th title="Days since the last contact (application date or latest dated note); open applications only">Quiet</th><th>Notes</th><th>Source</th></tr></thead>
<tbody>{table_rows(rows, show_deadline)}</tbody></table>
{unmatched_note}
</div>
<footer>Generated by Claude Code · ai-job-search · {today}</footer>
</div>
<script>{JS}</script></body></html>
"""


def build(root: str, today: str | None = None) -> tuple[str, dict]:
    """Return (html, stats) for the repo at `root`."""
    rows = read_tracker(os.path.join(root, "job_search_tracker.csv"))
    unmatched = merge_outcomes(rows, read_outcomes(root))
    today = today or date.today().isoformat()
    stats = compute_stats(rows, today)
    stats["unmatched"] = [f'{o["company"]} — {o["role"]}' for o in unmatched]
    return render(rows, stats, unmatched, today), stats


def main(argv: list[str] | None = None) -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="Generate the application tracker dashboard.")
    parser.add_argument("output", nargs="?", default=os.path.join(repo_root, "reports", "application-dashboard.html"),
                        help="output .html path (default: reports/application-dashboard.html)")
    parser.add_argument("--root", default=repo_root, help="repo root holding job_search_tracker.csv")
    args = parser.parse_args(argv)

    page, stats = build(args.root)
    output = os.path.expanduser(args.output)
    os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(page)

    b = stats["by_bucket"]
    print(f"Dashboard generated: {output}")
    print(f"Applications sent: {stats['sent']} · drafted, not yet sent: {stats['drafted']}")
    print(f"Active: {b['Active']} · Interview: {b['Interview']} · Offer: {b['Offer']} · "
          f"Hired: {b['Hired']} · Rejected/Closed: {b['Rejected/Closed']}")
    print(f"Funnel: {stats['past_screen_pct']}% progressed past resume screen")
    print(f"Quiet {QUIET_DAYS}+ days: {len(stats['quiet'])}" + (f" ({', '.join(stats['quiet'])})" if stats["quiet"] else ""))
    if stats["rejection_rate"] is not None:
        print(f"Rejection rate: {stats['rejection_rate']}% ({stats['true_rejections']} of {stats['resolved']} resolved"
              + (f", {stats['withdrawn']} withdrawn)" if stats["withdrawn"] else ")"))
    if stats["unrecognised"]:
        print("Unrecognised status values: " + ", ".join(stats["unrecognised"]))
    if stats["unmatched"]:
        print("Outcome files without a tracker row: " + "; ".join(stats["unmatched"]))
    if stats["other_sectors"]:
        print("Sectors grouped as Other (prefix the tracker value with a group, e.g. 'Healthcare: ...'; "
              "groups: " + ", ".join(SECTOR_GROUP_NAMES[:-1]) + "): " + "; ".join(stats["other_sectors"]))
    if stats["unrecorded_sectors"]:
        print("Sector not recorded: " + ", ".join(stats["unrecorded_sectors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
