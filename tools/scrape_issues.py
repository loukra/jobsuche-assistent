#!/usr/bin/env python3
"""Collect problems from the daily GitHub Actions scrape into a durable log.

Every problem a run hits - a portal CLI error, a failed detail fetch, a tool
call the workflow's allowlist refused, or the whole run aborting - becomes one
JSON line in job_scraper/scrape_issues.jsonl, committed with the run. After a
`git pull`, ask Claude locally to read that file and fix what is fixable
(a broken portal parser, a missing allowlist entry, ...).

  collect  read out/issues.json (written by Claude during the run) and the
           refused tool calls from the action's transcript; append them to
           the log, and add the refused calls to out/report.html so they
           show up in the mail
  failure  append one "run_failed" line naming the failed step and Claude's
           last message, and write out/failure.txt (the failure mail's body)
           plus out/transcript.json (its attachment)

Usage:
  python3 tools/scrape_issues.py collect --run-url URL [--exec-file PATH]
  python3 tools/scrape_issues.py failure --run-url URL [--exec-file PATH] [--outcomes JSON]
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "job_scraper" / "scrape_issues.jsonl"
OUT = ROOT / "out"


def append(lines: list[dict]) -> None:
    if not lines:
        return
    with LOG.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def stamp(run_url: str) -> dict:
    return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "run": run_url}


def refused_calls(exec_file: str | None) -> list[dict]:
    if not exec_file:
        return []
    try:
        messages = json.loads(Path(exec_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [d for m in messages if isinstance(m, dict) and m.get("type") == "result"
            for d in m.get("permission_denials") or [] if isinstance(d, dict)]


def add_to_report(denials: list[dict]) -> None:
    items = "".join(
        f"<li><code>{html.escape(str(d.get('tool_name', '?')))}</code>: "
        f"{html.escape(json.dumps(d.get('tool_input', {}), ensure_ascii=False)[:300])}</li>"
        for d in denials)
    block = ('<div style="margin-top:24px;font-family:sans-serif;font-size:13px;color:#555">'
             f"<b>Blockierte Werkzeug-Aufrufe ({len(denials)})</b> - von der Freigabeliste "
             f"im Workflow abgelehnt:<ul>{items}</ul></div>")
    report = OUT / "report.html"
    OUT.mkdir(exist_ok=True)
    text = report.read_text(encoding="utf-8") if report.exists() else "<p>Keine neuen Jobs.</p>"
    text = text.replace("</body>", block + "</body>", 1) if "</body>" in text else text + block
    report.write_text(text, encoding="utf-8")
    subject = OUT / "subject.txt"
    if not subject.exists():
        subject.write_text(f"Keine neuen Jobs – {len(denials)} blockierte Aufrufe", encoding="utf-8")


def cmd_collect(args) -> int:
    base = stamp(args.run_url)
    lines = []
    try:
        reported = json.loads((OUT / "issues.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reported = []
    for issue in reported if isinstance(reported, list) else []:
        if isinstance(issue, dict):
            lines.append({**base, "kind": "portal_or_step", **issue})

    denials = refused_calls(args.exec_file)
    for d in denials:
        lines.append({**base, "kind": "tool_refused", "tool": d.get("tool_name"),
                      "input": d.get("tool_input")})
    if denials:
        add_to_report(denials)

    append(lines)
    print(f"{len(lines)} issue(s) logged")
    return 0


# Step ids in the workflow, in run order, with the names shown in the mail.
STEPS = [("claude", "Run /scrape"), ("check", "Check the run finished"), ("collect", "Collect issues"),
         ("mail", "Send mail"), ("commit", "Commit seen jobs")]


def load_messages(exec_file: str | None) -> list:
    try:
        data = json.loads(Path(exec_file).read_text(encoding="utf-8")) if exec_file else []
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def last_words(messages: list) -> tuple[str, list[str]]:
    """Claude's final message and its last few tool calls with their results."""
    result = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("type") == "result"), None)
    final = ""
    if result:
        final = (f"[{result.get('subtype')}, is_error={result.get('is_error')}, "
                 f"{result.get('num_turns')} Schritte] {result.get('result') or ''}")
    else:
        texts = [c.get("text", "") for m in messages if isinstance(m, dict) and m.get("type") == "assistant"
                 for c in m.get("message", {}).get("content", []) if c.get("type") == "text"]
        final = texts[-1] if texts else "(keine Meldung von Claude - der Schritt lief nicht oder brach sofort ab)"

    calls, outputs = {}, []
    for m in messages:
        if not isinstance(m, dict):
            continue
        for c in m.get("message", {}).get("content", []) if isinstance(m.get("message"), dict) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                calls[c.get("id")] = f"{c.get('name')}: {json.dumps(c.get('input'), ensure_ascii=False)[:200]}"
            elif c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = " ".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                flag = "FEHLER " if c.get("is_error") else ""
                outputs.append(f"- {calls.get(c.get('tool_use_id'), '?')}\n  -> {flag}{' '.join(str(body).split())[:300]}")
    return final[:3000], outputs[-8:]


def cmd_failure(args) -> int:
    try:
        outcomes = json.loads(args.outcomes or "{}")
    except json.JSONDecodeError:
        outcomes = {}
    failed = next((name for sid, name in STEPS if outcomes.get(sid) == "failure"), "Einrichtung (vor Claude)")
    messages = load_messages(args.exec_file)
    final, recent = last_words(messages)

    append([{**stamp(args.run_url), "kind": "run_failed", "step": failed, "claude_last_message": final[:1000],
             "error": "The workflow aborted; see the run log and the mailed transcript."}])

    OUT.mkdir(exist_ok=True)
    body = [
        "Der Job-Scrape ist abgebrochen - bitte nachschauen.",
        "",
        f"Fehlgeschlagener Schritt: {failed}",
        f"Protokoll auf GitHub: {args.run_url}",
        "",
        "Letzte Meldung von Claude:",
        final,
        "",
        "Letzte Werkzeug-Aufrufe:",
        *(recent or ["(keine)"]),
        "",
        "Nicht verschickte Treffer kommen beim nächsten Lauf erneut (seen_jobs.json wurde nicht gespeichert).",
        "Der Fehler steht auch in job_scraper/scrape_issues.jsonl - nach git pull lokal mit Claude beheben.",
        "Das vollständige Claude-Protokoll hängt als transcript.json an.",
    ]
    (OUT / "failure.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    if args.exec_file and Path(args.exec_file).is_file():
        shutil.copyfile(args.exec_file, OUT / "transcript.json")
    else:
        (OUT / "transcript.json").write_text('{"note": "no Claude transcript - the run failed before Claude started"}\n')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    col = sub.add_parser("collect")
    col.add_argument("--run-url", required=True)
    col.add_argument("--exec-file")
    fail = sub.add_parser("failure")
    fail.add_argument("--run-url", required=True)
    fail.add_argument("--exec-file")
    fail.add_argument("--outcomes", help="JSON map of workflow step id -> outcome")
    args = ap.parse_args()
    return {"collect": cmd_collect, "failure": cmd_failure}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
