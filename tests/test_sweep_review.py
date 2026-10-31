"""Tests for tools/sweep_review.py - reading and storing a sweep's candidates.

The remote check decides which "remote" postings get dropped as hybrid before
anyone reads them, so its cases come from postings read on 2026-10-26 (phrases
shortened). store is the step that files a run: a read posting must never end
up in the unread index, and the sweep window must only move once it is filed.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import seen_jobs  # noqa: E402
import sweep_review as review  # noqa: E402


class RemoteVerdict(unittest.TestCase):
    def verdict(self, text):
        return review.remote_verdict(text)[0]

    def test_weekly_office_days_are_hybrid(self):
        for text in ["2 Tage Home-Office, 3 Tage im Office – so bleibst du flexibel.",
                     "Munich, four days in the office, one day remote.",
                     "This is a permanent hybrid position with 3 days per week in the office.",
                     "Mindestens 3 von 5 Tagen in unserem Büro in Pfaffenhofen. Remote-Tage sind möglich.",
                     "Able to be in our Cologne office 3 days a week.",
                     "2 days working from the office and 3 days of remote work, each week."]:
            self.assertEqual(self.verdict(text), "hybrid", text)

    def test_remote_wording_is_remote(self):
        for text in ["Remote-first with flexible working hours – office optional in Berlin.",
                     "Bis zu 100% Home-Office - Mobiles Arbeiten",
                     "Du arbeitest remote oder in unserem neu gebauten Büro in München.",
                     "Start immediately, remote from Germany, occasional on-site in Bochum.",
                     "Remote Arbeit (wir treffen uns nur gelegentlich in Münster)"]:
            self.assertEqual(self.verdict(text), "remote", text)

    def test_team_days_per_quarter_are_not_weekly_office_days(self):
        text = "Hybrides Arbeiten – in der Regel nur 3 Tage pro Quartal im Hamburger Büro."
        self.assertNotEqual(self.verdict(text), "hybrid")

    def test_the_word_hybrid_alone_decides_nothing(self):
        verdict, why = review.remote_verdict("Individuelle Arbeitsmodelle: vor Ort, hybrid oder remote.")
        self.assertEqual(verdict, "unclear")
        self.assertTrue(why)

    def test_location_independent_learning_is_not_remote_work(self):
        self.assertEqual(self.verdict("Die Lernwelt bietet Dir zeit- und ortsunabhängig 250 Seminare."), "unclear")

    def test_parse_pick(self):
        self.assertEqual(review.parse_pick("3,7-9"), {3, 7, 8, 9})


class Sample(unittest.TestCase):
    def test_the_audit_reads_unchosen_lines_only_once_each(self):
        out = Path(tempfile.mkdtemp())
        rows = [row(f"https://s.test/{i}", f"Role {i}", tier="core" if i < 8 else "edge", score=0)
                for i in range(12)]
        rows[0]["score"] = 20  # AUTO (remote line 11)
        rows[3]["dup_of"] = "https://s.test/2"
        (out / "sweep_candidates.json").write_text(json.dumps(rows), encoding="utf-8")
        fetched = []
        real = review.read_posting
        review.read_posting = lambda r: fetched.append(r["url"]) or {"description": "Remote-first."}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                review.cmd_detail(Namespace(out=out, auto=True, pick=None, sample=4, chars=100, delay=0))
        finally:
            review.read_posting = real
        details = json.loads((out / "details.json").read_text(encoding="utf-8"))
        why = {d["url"]: d["why"] for d in details}
        self.assertEqual(why["https://s.test/0"], "auto")
        self.assertEqual(sum(1 for w in why.values() if w == "sample"), 6)  # 4 core + 2 edge
        self.assertNotIn("https://s.test/3", why)  # a copy is never sampled
        self.assertEqual(len(fetched), len(set(fetched)))


def row(url, title, company="Acme", pass_="remote", **extra):
    return {"title": title, "company": company, "url": url, "location": "Remote", "posted_date": "2026-10-26",
            "portal": "linkedin-search", "source": "cli", "pass": pass_, "tier": "core", "score": 20, **extra}


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.out = self.dir / "out"
        self.out.mkdir()
        self.state = self.dir / "seen_jobs.json"
        self.state.write_text('{"seen": {}}', encoding="utf-8")
        self.index = self.dir / "seen_index.tsv"
        self.sweep_state = self.dir / "sweep_state.json"
        pending = datetime(2026, 10, 26, 8, tzinfo=timezone.utc).isoformat()
        self.sweep_state.write_text(json.dumps({"portals": {"linkedin": {
            "last_success": (datetime(2026, 10, 26, 8, tzinfo=timezone.utc) - timedelta(days=1)).isoformat(),
            "pending_success": pending}}}), encoding="utf-8")
        self.pending = pending
        rows = [row("https://x.test/1", "Senior .NET Engineer"),
                row("https://x.test/2", "Senior .NET Engineer", dup_of="https://x.test/1"),
                row("https://x.test/3", "Data Engineer")]
        (self.out / "sweep_candidates.json").write_text(json.dumps(rows), encoding="utf-8")
        (self.out / "sweep_skipped.json").write_text(json.dumps(
            [{"title": "Verkäufer", "company": "Shop", "url": "https://x.test/9", "portal": "stepstone-search"}]),
            encoding="utf-8")
        (self.out / "details.json").write_text(json.dumps([{"idx": 0, "url": "https://x.test/1"}]), encoding="utf-8")

    def store(self, verdicts):
        path = self.out / "verdicts.json"
        path.write_text(json.dumps(verdicts), encoding="utf-8")
        args = Namespace(out=self.out, verdicts=path, state=self.state, index=self.index,
                         sweep_state=self.sweep_state, today=date(2026, 10, 26), no_confirm=False,
                         audit=self.dir / "triage_audit.jsonl")
        with contextlib.redirect_stdout(io.StringIO()):
            return review.cmd_store(args)

    def test_files_read_postings_and_copies_in_seen_jobs_the_rest_in_the_index(self):
        self.store([{"url": "https://x.test/1", "fit": "high", "status": "new"}])
        seen = json.loads(self.state.read_text(encoding="utf-8"))["seen"]
        by_url = {e["url"]: e for e in seen.values()}
        self.assertEqual(by_url["https://x.test/1"]["status"], "new")
        self.assertEqual(set(by_url), {"https://x.test/1"})  # the copy is not ranked twice
        # The copy shares company+title with the lead, so it is already covered by
        # it; the unread candidate and the title-filtered posting get fingerprints.
        idx_urls, _ = seen_jobs.index_sets(seen_jobs.load_index(self.index, date(2026, 10, 26)))
        self.assertTrue({seen_jobs.fingerprint(seen_jobs.norm_url(u))
                         for u in ("https://x.test/3", "https://x.test/9")} <= idx_urls)
        res = json.loads(self.run_filter([row("https://x.test/2", "Senior .NET Engineer")]))
        self.assertEqual(res["new"], [])

    def run_filter(self, items):
        path = self.out / "probe.json"
        path.write_text(json.dumps(items), encoding="utf-8")
        tracker = self.dir / "tracker.csv"
        tracker.write_text("company,role\n", encoding="utf-8")
        return subprocess.run([sys.executable, str(REPO / "tools" / "seen_jobs.py"), "filter", "--in", str(path),
                               "--state", str(self.state), "--index", str(self.index), "--tracker", str(tracker),
                               "--today", "2026-10-26"], capture_output=True, text=True, check=True).stdout

    def test_a_read_posting_carries_its_salary_band_and_figure(self):
        (self.out / "details.json").write_text(json.dumps([{"idx": 0, "url": "https://x.test/1",
            "pay": {"band": {"min": 65000, "max": 85000, "period": "year", "quote": "65.000 - 85.000 €"},
                    "wish": 79000, "label": "65k–85k → 79k"}}]), encoding="utf-8")
        self.store([{"url": "https://x.test/1", "fit": "high", "status": "new"}])
        stored = next(iter(json.loads(self.state.read_text(encoding="utf-8"))["seen"].values()))
        self.assertEqual((stored["salary_wish"], stored["salary_label"]), (79000, "65k–85k → 79k"))

    def test_details_without_pay_are_read_from_their_text(self):
        (self.out / "details.json").write_text(json.dumps([{"idx": 0, "url": "https://x.test/1",
            "text": "Gehalt: 70.000 bis 90.000 EUR brutto"}]), encoding="utf-8")
        self.store([{"url": "https://x.test/1", "fit": "high", "status": "new"}])
        stored = next(iter(json.loads(self.state.read_text(encoding="utf-8"))["seen"].values()))
        self.assertEqual(stored["salary_wish"], 84000)

    def test_confirms_the_sweep_window_only_after_filing(self):
        self.store([{"url": "https://x.test/1", "fit": "high", "status": "new"}])
        state = json.loads(self.sweep_state.read_text(encoding="utf-8"))["portals"]["linkedin"]
        self.assertEqual(state, {"last_success": self.pending})

    def test_a_sampled_fit_is_logged_as_a_triage_miss(self):
        (self.out / "details.json").write_text(json.dumps([
            {"idx": 0, "url": "https://x.test/1", "why": "auto"},
            {"idx": 2, "url": "https://x.test/3", "why": "sample", "title": "Data Engineer", "company": "Acme"}]),
            encoding="utf-8")
        self.store([{"url": "https://x.test/1", "fit": "high", "status": "new"},
                    {"url": "https://x.test/3", "fit": "medium", "status": "new"}])
        line = json.loads((self.dir / "triage_audit.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((line["auto"], line["sampled"]), (1, 1))
        self.assertEqual(line["missed"], ["Data Engineer | Acme (medium)"])
        self.assertEqual(line["fits_by_route"], {"auto": 1, "picked": 0, "sample": 1})

    def test_refuses_when_a_read_posting_has_no_verdict(self):
        with self.assertRaises(SystemExit):
            self.store([])
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["seen"], {})
        self.assertIn("pending_success", self.sweep_state.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
