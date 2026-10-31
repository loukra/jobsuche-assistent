"""Tests for the seen index (tools/seen_jobs.py index).

The sweep reads thousands of postings a day that no fit check ever reads.
Stored as full seen_jobs.json entries they grew the file from 1.7 to 9.3 MB in
one run (2026-10-26), so they live as expiring fingerprints instead. These pin
that a fingerprint still dedups the posting, and that the index stays bounded.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "seen_jobs.py"


def posting(url, title="Verkäufer (m/w/d)", company="Kaufhaus GmbH", portal="stepstone-search"):
    return {"title": title, "company": company, "url": url, "portal": portal, "status": "skipped", "fit": "low"}


class SeenIndex(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.state = self.dir / "seen_jobs.json"
        self.state.write_text('{"seen": {}}', encoding="utf-8")
        self.index = self.dir / "seen_index.tsv"
        self.tracker = self.dir / "tracker.csv"
        self.tracker.write_text("company,role\n", encoding="utf-8")

    def run_tool(self, command, items, today="2026-10-26"):
        path = self.dir / f"{command}.json"
        path.write_text(json.dumps(items), encoding="utf-8")
        extra = ["--tracker", str(self.tracker)] if command == "filter" else []
        out = subprocess.run([sys.executable, str(TOOL), command, "--in", str(path), "--state", str(self.state),
                              "--index", str(self.index), "--today", today, *extra],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_a_fresh_checkout_without_history_treats_everything_as_new(self):
        self.state.unlink()
        out = self.run_tool("filter", [posting("https://x/1")])
        self.assertEqual(len(out["new"]), 1)

    def test_an_indexed_posting_is_not_new_again(self):
        self.run_tool("index", [posting("https://www.stepstone.de/job/1?utm_source=x")])
        res = self.run_tool("filter", [posting("https://stepstone.de/job/1")])
        self.assertEqual(res["new"], [])
        self.assertEqual(res["dropped"]["seen_index"], 1)

    def test_the_same_posting_under_another_url_is_caught_by_company_and_title(self):
        self.run_tool("index", [posting("https://www.stepstone.de/job/1")])
        res = self.run_tool("filter", [posting("https://www.xing.com/jobs/2", company="Kaufhaus")])
        self.assertEqual(res["new"], [])

    def test_a_posting_without_company_matches_by_url_only(self):
        # A bare title like "Sales Manager" must not hide every other posting with it.
        self.run_tool("index", [posting("https://jobs.instaffo.com/de/job/a", "sales manager", None)])
        res = self.run_tool("filter", [posting("https://jobs.instaffo.com/de/job/b", "sales manager", None)])
        self.assertEqual(len(res["new"]), 1)

    def test_a_line_is_short(self):
        self.run_tool("index", [posting("https://www.stepstone.de/job/1")])
        line = self.index.read_text(encoding="utf-8")
        self.assertEqual(line, line.strip() + "\n")
        self.assertLess(len(line), 50)
        self.assertTrue(line.startswith("2026-10-26\tstepstone\t"))

    def test_old_fingerprints_expire(self):
        self.run_tool("index", [posting("https://www.stepstone.de/job/1")], today="2026-06-01")
        res = self.run_tool("index", [posting("https://www.stepstone.de/job/2")], today="2026-10-26")
        self.assertEqual((res["added"], res["expired"], res["size"]), (1, 1, 1))
        self.assertEqual(len(self.run_tool("filter", [posting("https://www.stepstone.de/job/1", company="Other")])["new"]), 1)

    def test_indexing_twice_adds_nothing(self):
        self.run_tool("index", [posting("https://www.stepstone.de/job/1")])
        res = self.run_tool("index", [posting("https://www.stepstone.de/job/1")])
        self.assertEqual((res["added"], res["already_present"], res["size"]), (0, 1, 1))

    def test_merge_is_a_line_union(self):
        attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("job_scraper/seen_index.tsv merge=union", attrs)


if __name__ == "__main__":
    unittest.main()
