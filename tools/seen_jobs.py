#!/usr/bin/env python3
"""State helper for /scrape: dedup candidates and append entries in code.

seen_jobs.json is append-only and grows for the life of the workspace, so
reading it into the model's context to dedup by eye (and re-emitting it to
store new entries) costs more on every run. The daily GitHub Actions scrape
uses this instead, the same way /rank uses tools/rank_state.py.

  filter   read candidate postings (JSON array) and print only those not yet
           in seen_jobs.json (by URL, canonical key, or company+title) and not
           already in job_search_tracker.csv (company+role)
  add      append entries (JSON array) under their tools/job_key.py key;
           existing keys are left untouched
  index    record postings no fit check read (title-filter and title-only
           skips) as fingerprints in seen_index.tsv, and drop fingerprints
           older than INDEX_MAX_AGE days
  merge    git merge driver: union of both sides' entries, so a local /rank
           and the daily scrape never conflict on the file

Usage:
  python3 tools/seen_jobs.py filter --in candidates.json
  python3 tools/seen_jobs.py add --in entries.json
  python3 tools/seen_jobs.py index --in out/sweep_skipped.json
  python3 tools/seen_jobs.py merge BASE OURS THEIRS

Wire the merge driver once per clone:
  git config merge.seenjobs.driver "python3 tools/seen_jobs.py merge %O %A %B"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from job_key import make_key  # noqa: E402

# Self-contained rather than importing tools/rank_state.py: this file also runs
# as a git merge driver on the laptop, whose python3 may predate 3.10 syntax.
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "job_scraper" / "seen_jobs.json"
TRACKER = ROOT / "job_search_tracker.csv"
# The sweep reads thousands of postings a day, nearly all ruled out by title.
# Kept in seen_jobs.json at ~580 bytes each, they grew it by megabytes per run
# (1.7 -> 9.3 MB on the first sweep, 2026-10-26); a fingerprint line is ~45
# bytes and expires. 90 days is far past the sweep's 14-day window; an undated
# posting still online after that (XING, Workwise, Instaffo) is simply judged
# again.
INDEX = ROOT / "job_scraper" / "seen_index.tsv"
INDEX_MAX_AGE = 90

# Later in the lifecycle wins when both sides of a merge hold the same key.
STATUS_ORDER = {"skipped": 0, "new": 1, "ranked": 2, "expired": 3}


def load_state(path: Path) -> tuple[dict, dict]:
    if not path.exists():  # a fresh checkout before its first /scrape
        doc: dict = {"seen": {}}
        return doc, doc["seen"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"{path}: {exc}")
    seen = doc.get("seen") if isinstance(doc, dict) else None
    if not isinstance(seen, dict):
        sys.exit(f"{path}: expected an object with a 'seen' map")
    return doc, seen


def save_state(path: Path, doc: dict) -> None:
    """Atomic replace: a half-written seen_jobs.json loses the scrape history."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".seen_jobs.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


# Portals disagree on the legal form ("Acme Defence and Space" on LinkedIn,
# "... GmbH" in the tracker), so company matching ignores it.
LEGAL_FORMS = {"gmbh", "mbh", "ag", "se", "kg", "kgaa", "co", "ug", "haftungsbeschrankt",
               "haftungsbeschraenkt", "ev", "ohg", "gbr", "ltd", "inc", "llc", "plc", "bv",
               "nv", "sa", "sarl", "srl", "corp", "corporation", "limited"}


def norm_company(text) -> str:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower().replace("ä", "a").replace("ü", "u").replace("ö", "o"))
    kept = [w for w in words if w not in LEGAL_FORMS]
    return "".join(kept or words)


def tracker_pairs(path: Path) -> set:
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {(norm_company(r.get("company")), norm(r.get("role"))) for r in csv.DictReader(fh) if norm(r.get("company"))}


def read_items(path: Path) -> list[dict]:
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"{path}: {exc}")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        sys.exit(f"{path}: expected a JSON array of objects")
    return items


TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|feedid|pk_campaign|pk_kwd|trk|trackingid|refid|src)$", re.I)


def norm_url(url) -> str:
    """Compare URLs without tracking noise, but keep everything that can
    identify a posting: some career sites put the posting id in the query
    (`?jobid=00007769`) or the fragment (`#position,id=...`)."""
    parsed = urlsplit(str(url or "").strip())
    if not parsed.netloc:
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                       if not TRACKING_PARAMS.match(k)])
    fragment = parsed.fragment if "id=" in parsed.fragment else ""
    host = parsed.netloc.lower().removeprefix("www.")
    return urlunsplit(("", host, parsed.path.rstrip("/"), query, fragment)).lower()


def fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def fingerprints(item: dict) -> tuple[str, str]:
    """(url, company+title) fingerprints; "-" where the posting gives none. A
    posting without a company gets no pair fingerprint: a bare title such as
    "Softwareentwickler" would match every other company-less posting."""
    url = norm_url(item.get("url"))
    company = norm_company(item.get("company"))
    return (fingerprint(url) if url else "-",
            fingerprint(f"{company}|{norm(item.get('title'))}") if company else "-")


def load_index(path: Path, today: date, max_age: int = INDEX_MAX_AGE) -> list[list[str]]:
    """Index rows [date, portal, url_fp, pair_fp] younger than max_age days."""
    if not path.is_file():
        return []
    cutoff = (today - timedelta(days=max_age)).isoformat()
    rows = [line.rstrip("\n").split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if len(r) == 4 and r[0] >= cutoff]


def index_sets(rows: list[list[str]]) -> tuple[set, set]:
    return {r[2] for r in rows} - {"-"}, {r[3] for r in rows} - {"-"}


def cmd_filter(args) -> int:
    _, seen = load_state(args.state)
    urls = {norm_url(e.get("url")) for e in seen.values() if isinstance(e, dict)} - {""}
    pairs = {(norm_company(e.get("company")), norm(e.get("title"))) for e in seen.values() if isinstance(e, dict)}
    applied = tracker_pairs(args.tracker)
    index_urls, index_pairs = index_sets(load_index(args.index, args.today))

    fresh, dropped = [], {"seen_url": 0, "seen_key": 0, "seen_company_title": 0, "seen_index": 0, "tracker": 0}
    for item in read_items(args.input):
        company, title, url = item.get("company") or "", item.get("title") or "", item.get("url") or ""
        pair = (norm_company(company), norm(title))
        url_fp, pair_fp = fingerprints(item)
        if norm_url(url) and norm_url(url) in urls:
            dropped["seen_url"] += 1
        elif make_key(company, title, url) in seen:
            dropped["seen_key"] += 1
        elif pair in pairs:
            dropped["seen_company_title"] += 1
        elif url_fp in index_urls or pair_fp in index_pairs:
            dropped["seen_index"] += 1
        elif pair in applied:
            dropped["tracker"] += 1
        else:
            fresh.append(item)
    print(json.dumps({"new": fresh, "dropped": dropped}, indent=2, ensure_ascii=False))
    return 0


def cmd_add(args) -> int:
    doc, seen = load_state(args.state) if args.state.is_file() else ({"seen": {}}, None)
    if seen is None:
        seen = doc["seen"]
    added, kept = [], 0
    for item in read_items(args.input):
        key = make_key(item.get("company") or "", item.get("title") or "", item.get("url") or "")
        if key in seen:
            kept += 1
            continue
        item.setdefault("first_seen", args.today.isoformat())
        seen[key] = item
        added.append(key)
    save_state(args.state, doc)
    print(json.dumps({"added": len(added), "already_present": kept, "keys": added}, indent=2))
    return 0


def write_index(path: Path, rows: list[list[str]]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".seen_index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines("\t".join(r) + "\n" for r in rows)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cmd_index(args) -> int:
    total = sum(1 for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()) \
        if args.index.is_file() else 0
    rows = load_index(args.index, args.today)
    urls, pairs = index_sets(rows)
    added = kept = 0
    for item in read_items(args.input):
        url_fp, pair_fp = fingerprints(item)
        if url_fp == "-" and pair_fp == "-":
            continue
        if (url_fp != "-" and url_fp in urls) or (pair_fp != "-" and pair_fp in pairs):
            kept += 1
            continue
        portal = str(item.get("portal") or "-").removesuffix("-search")
        rows.append([args.today.isoformat(), portal, url_fp, pair_fp])
        urls.add(url_fp)
        pairs.add(pair_fp)
        added += 1
    write_index(args.index, rows)
    print(json.dumps({"added": added, "already_present": kept, "expired": total - (len(rows) - added),
                      "size": len(rows)}, indent=2))
    return 0


def pick(a: dict, b: dict) -> dict:
    """The entry further along its lifecycle; ties go to the later rank_date."""
    rank = lambda e: (STATUS_ORDER.get(e.get("status"), 2), e.get("rank_date") or "")  # noqa: E731
    return b if rank(b) > rank(a) else a


def cmd_merge(args) -> int:
    def load(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"seen": {}}

    ours, theirs = load(args.ours), load(args.theirs)
    merged = dict(ours.get("seen", {}))
    for key, entry in theirs.get("seen", {}).items():
        merged[key] = pick(merged[key], entry) if key in merged else entry
    ours["seen"] = merged
    save_state(args.ours, ours)
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", type=Path, default=STATE)
    common.add_argument("--today", type=date.fromisoformat, default=date.today())
    common.add_argument("--index", type=Path, default=INDEX)

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    flt = sub.add_parser("filter", parents=[common])
    flt.add_argument("--in", dest="input", type=Path, required=True)
    flt.add_argument("--tracker", type=Path, default=TRACKER)
    add = sub.add_parser("add", parents=[common])
    add.add_argument("--in", dest="input", type=Path, required=True)
    idx = sub.add_parser("index", parents=[common])
    idx.add_argument("--in", dest="input", type=Path, required=True)
    mrg = sub.add_parser("merge")
    mrg.add_argument("base", type=Path)
    mrg.add_argument("ours", type=Path)
    mrg.add_argument("theirs", type=Path)

    args = ap.parse_args()
    return {"filter": cmd_filter, "add": cmd_add, "index": cmd_index, "merge": cmd_merge}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
