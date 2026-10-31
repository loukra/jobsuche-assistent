#!/usr/bin/env python3
"""Read and store a sweep's candidates for /scrape (after tools/scrape_sweep.py).

  detail   fetch the full posting for every AUTO-read candidate (and any picked
           by index from sweep_titles.txt) into <out>/details.json, with a
           remote verdict read from the text, any salary figures and, where the
           posting names a band, the figure to state (tools/salary_band.py);
           resumable, postings already fetched are skipped
  store    write the run into the state: every posting with a verdict to
           seen_jobs.json, everything else - unread candidates, copies of read
           ones, sweep_skipped.json - to the seen index; then confirm the sweep
           window

Usage:
  python3 tools/sweep_review.py detail --out out --auto --sample 10
  python3 tools/sweep_review.py detail --out out --pick 812,1033-1035
  python3 tools/sweep_review.py store --out out --verdicts out/verdicts.json

verdicts.json is a JSON array, one object per posting read:
  {"url": "...", "fit": "high|medium|low", "status": "new|skipped|expired",
   "deadline": "YYYY-MM-DD" | null, "note": "optional, one line"}
Every posting in details.json needs one: store refuses to run otherwise, so a
read posting is never filed as unread.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import salary_band  # noqa: E402
import scrape_sweep as sweep  # noqa: E402
import seen_jobs  # noqa: E402

TOOLS = Path(__file__).resolve().parent
# Postings the triage left unread but a full read found to fit: the triage's miss
# rate, run by run (store appends one line per run with a sample).
AUDIT_LOG = TOOLS.parent / "job_scraper" / "triage_audit.jsonl"

# --- remote verdict ------------------------------------------------------------
#
# Portal remote filters let hybrid roles through: of 41 remote titles read on
# 2026-10-26, 11 named weekly office days. These patterns come from those texts.

_NUM = r"(?:\d|ein|einen|zwei|drei|vier|fünf|one|two|three|four|five)"
_PLACE = r"(?:büro|office|vor ort|on-?site|präsenz|standort)"
OFFICE_DAYS = re.compile(
    rf"{_NUM}\s*(?:von\s*\d\s*)?(?:tage?n?|days?)\b[^.;]{{0,45}}?{_PLACE}"
    rf"|{_PLACE}[^.;]{{0,45}}?{_NUM}\s*(?:tage?n?|days?)\s*(?:pro|per|a|in der|die|each|the)\s*(?:woche|week)",
    re.I,
)
# "3 Tage pro Quartal im Büro" is remote with team days, not hybrid.
RARE_VISITS = re.compile(r"quartal|quarter|monat|month|jahr|year|gelegentlich|occasional", re.I)
REMOTE = re.compile(
    r"100\s?%\s?(?:remote|home.?office|mobil)|fully remote|full[- ]remote|remote[- ]first|vollständig remote"
    r"|komplett remote|voll remote|ortsunabhängig(?:es|em)? arbeit|arbeit\w* ortsunabhängig|remote (?:from|aus|in) (?:germany|deutschland|der eu|the eu)"
    r"|bis zu 100\s?%\s?(?:home.?office|remote|mobil)|du arbeitest remote|remote arbeit|remote work from"
    r"|freie (?:wahl (?:des|deines) )?arbeitsort|arbeitsort-wahl|work from anywhere|deutschlandweit remote"
    r"|no fixed office|kein(?:e)? (?:fester|feste) (?:büro|arbeitsplatz|präsenz)",
    re.I,
)
HYBRID = re.compile(r"\bhybrid", re.I)
CONTRACT = re.compile(r"freelance|freiberuf|contractor|hourly|stundenbasis|werkvertrag|freie mitarbeit", re.I)
SALARY = re.compile(r"\d{2,3}[.,]?\d{3}\s?(?:€|eur)|€\s?\d{2,3}[.,]?\d{3}|\b\d{2,3}\s?k\b|\b\d{2,3}\s?tsd", re.I)


def remote_verdict(text: str) -> tuple[str, list[str]]:
    """'remote', 'hybrid' (weekly office days) or 'unclear', with the text
    around what decided it (for unclear: any mention of hybrid work)."""
    text = re.sub(r"\s+", " ", text or "")
    weekly = [m for m in OFFICE_DAYS.finditer(text) if not RARE_VISITS.search(m.group(0))]
    positive = list(REMOTE.finditer(text))

    def quote(m) -> str:
        return text[max(0, m.start() - 60):m.end() + 60].strip()

    if weekly:
        return "hybrid", [quote(m) for m in weekly[:2]]
    if positive:
        return "remote", [quote(m) for m in positive[:2]]
    # "hybrid" alone decides nothing: "vor Ort, hybrid oder remote" offers all three.
    return "unclear", [quote(m) for m in list(HYBRID.finditer(text))[:2]]


# --- detail ------------------------------------------------------------------


def parse_pick(spec: str | None) -> set[int]:
    picked: set[int] = set()
    for part in filter(None, (spec or "").split(",")):
        lo, _, hi = part.strip().partition("-")
        picked.update(range(int(lo), int(hi or lo) + 1))
    return picked


def load_candidates(out: Path) -> list[dict]:
    return json.loads((out / "sweep_candidates.json").read_text(encoding="utf-8"))


def read_posting(row: dict) -> dict:
    portal = row["portal"].removesuffix("-search")
    if portal == "watchlist":  # an employer's own career page, no portal CLI
        try:
            return {"description": sweep.strip_html(sweep.fetch(row["url"]))}
        except Exception as exc:  # noqa: BLE001 - reported verbatim
            return {"error": f"{type(exc).__name__}: {exc}"}
    # freehire's detail takes its slug, not the employer URL it links to.
    ref = row.get("id") if portal == "freehire" and row.get("id") else row["url"]
    return sweep.run_cli(portal, ["detail", str(ref)], timeout=120)


def cmd_detail(args) -> int:
    rows = load_candidates(args.out)
    picked = parse_pick(args.pick)
    bad = sorted(i for i in picked if i >= len(rows))
    if bad:
        sys.exit(f"no candidate with index {bad[0]} (sweep_candidates.json holds {len(rows)})")
    wanted = [i for i, r in enumerate(rows) if not r.get("dup_of") and (
        i in picked or (args.auto and sweep.auto_read(r)))]
    # The audit: a few lines nobody chose, read in full anyway. A fit among them
    # is a posting the triage would have lost. Seeded by the run's file, so a
    # rerun of detail draws the same sample.
    sampled: set[int] = set()
    if args.sample:
        rng = random.Random((args.out / "sweep_candidates.json").stat().st_size)
        rest = [i for i, r in enumerate(rows) if not r.get("dup_of") and i not in wanted]
        core = [i for i in rest if rows[i].get("tier") == "core"]
        edge = [i for i in rest if rows[i].get("tier") != "core"]
        sampled = set(rng.sample(core, min(args.sample, len(core))) +
                      rng.sample(edge, min(max(1, args.sample // 2), len(edge))))
        wanted += sorted(sampled)
    path = args.out / "details.json"
    details = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    done = {d["idx"] for d in details}
    todo = [i for i in wanted if i not in done]
    print(f"{len(wanted)} to read, {len(wanted) - len(todo)} already fetched", file=sys.stderr)
    for n, i in enumerate(todo, 1):
        row = rows[i]
        data = read_posting(row)
        text = str(data.get("description") or "") if "error" not in data else ""
        verdict, why = remote_verdict(text)
        details.append({
            "idx": i, "url": row["url"], "title": row.get("title"), "company": row.get("company"),
            "location": row.get("location"), "area": sweep.area(row), "score": row.get("score"),
            "copies": row.get("copies", 1), "error": data.get("error"),
            "why": "sample" if i in sampled else ("auto" if sweep.auto_read(row) else "picked"),
            "remote": verdict, "remote_evidence": why,
            "contract": bool(CONTRACT.search(text)), "salary": sorted(set(SALARY.findall(text)))[:3],
            # Read from the full text: the excerpt below often ends before the pay section.
            "pay": salary_band.assess(text, portal_salary=data.get("salary") or row.get("portal_salary"),
                                      portal=row.get("portal")),
            "text": re.sub(r"\s+", " ", text)[:args.chars],
        })
        path.write_text(json.dumps(details, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{n}/{len(todo)}] {i} {verdict:8} {(row.get('title') or '')[:60]}", file=sys.stderr)
        time.sleep(args.delay)
    errors = [d for d in details if d.get("error")]
    print(json.dumps({"read": len(details), "errors": len(errors),
                      "remote": {v: sum(1 for d in details if d["area"] == "remote" and d["remote"] == v)
                                 for v in ("remote", "hybrid", "unclear")}}, indent=2))
    return 0


# --- store -------------------------------------------------------------------


def run_tool(command: str, items: list[dict], out: Path, extra: list[str]) -> dict:
    path = out / f"_{command}.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(TOOLS / "seen_jobs.py"), command, "--in", str(path), *extra],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"seen_jobs {command} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def entry(row: dict, **fields) -> dict:
    return {"title": row.get("title"), "company": row.get("company"), "url": row["url"],
            "location": row.get("location"), "posted_date": row.get("posted_date"), "deadline": None,
            "portal": row.get("portal"), "source": "cli", **fields}


def pay_fields(detail: dict | None) -> dict:
    """The salary band and suggested figure a read posting carries into seen_jobs.json."""
    pay = (detail or {}).get("pay")
    if pay is None and detail and detail.get("text"):  # details.json written before "pay" existed
        pay = salary_band.assess(detail["text"])
    if not pay or not pay.get("label"):
        return {}
    return {"salary_band": pay.get("band") or pay.get("single"), "salary_wish": pay.get("wish"),
            "salary_label": pay["label"]}


def audit_line(read: list[dict], by_url: dict, today: date) -> dict | None:
    """What the run read and why, and which sampled postings turned out to fit."""
    if not read:
        return None
    why = [d.get("why", "picked") for d in read]
    verdict = lambda d: by_url.get(seen_jobs.norm_url(d["url"]), {})  # noqa: E731
    sample = [d for d in read if d.get("why") == "sample"]
    missed = [f"{d.get('title')} | {d.get('company')} ({verdict(d).get('fit')})" for d in sample
              if verdict(d).get("fit") in ("high", "medium")]
    return {"date": today.isoformat(), "auto": why.count("auto"), "picked": why.count("picked"),
            "sampled": len(sample), "missed": missed,
            "fits_by_route": {w: sum(1 for d in read if d.get("why", "picked") == w
                                     and verdict(d).get("fit") in ("high", "medium"))
                              for w in ("auto", "picked", "sample")}}


def cmd_store(args) -> int:
    rows = load_candidates(args.out)
    verdicts = json.loads(args.verdicts.read_text(encoding="utf-8")) if args.verdicts else []
    by_url = {seen_jobs.norm_url(v["url"]): v for v in verdicts}
    details_path = args.out / "details.json"
    read = json.loads(details_path.read_text(encoding="utf-8")) if details_path.is_file() else []
    missing = [d["url"] for d in read if seen_jobs.norm_url(d["url"]) not in by_url]
    if missing:
        sys.exit(f"{len(missing)} read posting(s) without a verdict, e.g. {missing[0]}")
    for v in verdicts:
        if v.get("fit") not in ("high", "medium", "low") or v.get("status") not in ("new", "skipped", "expired"):
            sys.exit(f"bad verdict for {v.get('url')}: fit and status are required")

    detail_by_url = {seen_jobs.norm_url(d["url"]): d for d in read}
    keep, unread = [], []
    for row in rows:
        url = seen_jobs.norm_url(row["url"])
        own = by_url.get(url)
        if own:
            keep.append(entry(row, fit=own["fit"], status=own["status"],
                              deadline=own.get("deadline"), note=own.get("note"),
                              **pay_fields(detail_by_url.get(url))))
        else:
            # Unread, or a copy of a read posting in another city or board: a
            # fingerprint keeps it from coming back, only the lead goes to /rank.
            unread.append(row)
    # Verdicts for postings outside the sweep (focus-area queries) are stored too.
    swept = {seen_jobs.norm_url(r["url"]) for r in rows}
    keep += [{**v, "source": v.get("source", "cli")} for v in verdicts if seen_jobs.norm_url(v["url"]) not in swept]

    skipped_path = args.out / "sweep_skipped.json"
    unread += json.loads(skipped_path.read_text(encoding="utf-8")) if skipped_path.is_file() else []
    today = ["--today", args.today.isoformat()]
    added = run_tool("add", keep, args.out, ["--state", str(args.state), *today])
    indexed = run_tool("index", unread, args.out, ["--index", str(args.index), *today])
    print(json.dumps({"seen_jobs": {"added": added["added"], "already_present": added["already_present"]},
                      "index": {k: indexed[k] for k in ("added", "already_present", "expired", "size")},
                      "new_for_rank": sum(1 for e in keep if e.get("status") == "new")}, indent=2))
    audit = audit_line(read, by_url, args.today)
    if audit:
        with args.audit.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(audit, ensure_ascii=False) + "\n")
        print(f"triage audit: {len(audit['missed'])} fit(s) among {audit['sampled']} sampled unread titles"
              + "".join(f"\n  missed: {m}" for m in audit["missed"]))
    if not args.no_confirm:
        sweep.confirm(args.sweep_state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    det = sub.add_parser("detail")
    det.add_argument("--out", type=Path, required=True)
    det.add_argument("--auto", action="store_true", help="every AUTO line of sweep_titles.txt")
    det.add_argument("--pick", help="indices from sweep_titles.txt, e.g. 12,40-44")
    det.add_argument("--sample", type=int, default=0,
                     help="also read this many random unread core titles (and half as many edge) as an audit")
    det.add_argument("--chars", type=int, default=2500, help="posting text kept per posting")
    det.add_argument("--delay", type=float, default=1.2)
    sto = sub.add_parser("store")
    sto.add_argument("--out", type=Path, required=True)
    sto.add_argument("--verdicts", type=Path)
    sto.add_argument("--state", type=Path, default=seen_jobs.STATE)
    sto.add_argument("--index", type=Path, default=seen_jobs.INDEX)
    sto.add_argument("--sweep-state", type=Path, default=sweep.STATE)
    sto.add_argument("--today", type=date.fromisoformat, default=date.today())
    sto.add_argument("--no-confirm", action="store_true")
    sto.add_argument("--audit", type=Path, default=AUDIT_LOG)
    args = ap.parse_args()
    if args.command == "detail" and not (args.auto or args.pick or args.sample):
        ap.error("detail needs --auto, --pick, --sample or a mix")
    return {"detail": cmd_detail, "store": cmd_store}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
