"""Tests for tools/scrape_sweep.py - the exhaustive portal sweep behind /scrape.

The sweep exists because page-1 sampling lost postings on almost every portal
(measured 2026-10-26). These pin the parts that decide whether a posting is
reached at all: paging until the portal runs out, the window that catches up
after a missed run, and the title filter, which must never drop a posting that
was ever rated a fit.
"""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import scrape_sweep as sweep  # noqa: E402

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


def pages_of(rows, size, total=None, repeat_last=False):
    """A fake portal: `rows` split into pages; past the end it returns an empty
    page, or (LinkedIn-style) the last page again."""
    chunks = [rows[i:i + size] for i in range(0, len(rows), size)]

    def fetch(page):
        if page <= len(chunks):
            body = chunks[page - 1]
        else:
            body = chunks[-1] if repeat_last and chunks else []
        meta = {"total": total} if total is not None else {}
        return {"meta": meta, "results": body}
    return fetch


def jobs(n):
    return [{"id": str(i), "title": f"Job {i}"} for i in range(n)]


class Paginate(unittest.TestCase):
    def test_reads_every_page_until_an_empty_one(self):
        res = sweep.paginate(pages_of(jobs(47), 10), 10, 100, sleep=lambda s: None)
        self.assertEqual(res["report"]["results"], 47)
        self.assertEqual(res["report"]["end"], "empty page")

    def test_stops_at_the_portal_total(self):
        calls = []
        fetch = pages_of(jobs(50), 25, total=50)
        res = sweep.paginate(lambda p: calls.append(p) or fetch(p), 25, 100, sleep=lambda s: None)
        self.assertEqual(res["report"]["results"], 50)
        self.assertEqual(calls, [1, 2])

    def test_stops_when_the_portal_repeats_its_last_page(self):
        res = sweep.paginate(pages_of(jobs(30), 10, repeat_last=True), 10, 100, sleep=lambda s: None)
        self.assertEqual(res["report"]["results"], 30)
        self.assertEqual(res["report"]["end"], "no new results")

    def test_without_stale_stop_a_page_of_repeats_does_not_end_it(self):
        # XING reshuffles: a page with nothing new can be followed by new ones.
        rows = jobs(40)
        served = {1: rows[0:10], 2: rows[0:10], 3: rows[0:10], 4: rows[10:40], 5: []}
        fetch = lambda p: {"meta": {}, "results": served.get(p, [])}  # noqa: E731
        stopped = sweep.paginate(fetch, 10, 10, sleep=lambda s: None)
        full = sweep.paginate(fetch, 10, 10, sleep=lambda s: None, stale_stop=False)
        self.assertEqual(stopped["report"]["results"], 10)
        self.assertEqual(full["report"]["results"], 40)

    def test_coverage_shows_postings_the_portal_counted_but_never_served(self):
        res = sweep.paginate(pages_of(jobs(30), 10, total=40), 10, 3, sleep=lambda s: None)
        self.assertEqual(res["report"]["coverage"], 0.75)

    def test_a_cap_is_reported_not_passed_off_as_done(self):
        res = sweep.paginate(pages_of(jobs(100), 10), 10, 3, sleep=lambda s: None)
        self.assertEqual(res["report"]["results"], 30)
        self.assertEqual(res["report"]["end"], "capped")

    def test_a_failed_page_is_retried_once_then_reported(self):
        calls = []

        def fetch(page):
            calls.append(page)
            return {"error": "HTTP 503"}
        res = sweep.paginate(fetch, 10, 10, sleep=lambda s: None)
        self.assertEqual(calls, [1, 1])
        self.assertEqual(res["report"]["end"], "error")
        self.assertIn("HTTP 503", res["report"]["error"])

    def test_a_transient_failure_does_not_end_the_sweep(self):
        fetch = pages_of(jobs(25), 10)
        failed = set()

        def flaky(page):
            if page == 2 and page not in failed:
                failed.add(page)
                return {"error": "timeout"}
            return fetch(page)
        res = sweep.paginate(flaky, 10, 10, sleep=lambda s: None)
        self.assertEqual(res["report"]["results"], 25)


class Window(unittest.TestCase):
    def state(self, hours_ago):
        return {"portals": {"stepstone": {"last_success": (NOW - timedelta(hours=hours_ago)).isoformat()}}}

    def test_no_state_uses_the_default(self):
        self.assertEqual(sweep.window_days({}, "stepstone", NOW), sweep.DEFAULT_DAYS)

    def test_twice_daily_runs_need_one_day(self):
        self.assertEqual(sweep.window_days(self.state(10), "stepstone", NOW), 1)

    def test_monday_morning_reaches_back_over_the_weekend(self):
        # Friday 17:50 -> Monday 08:00 is 62 hours.
        self.assertEqual(sweep.window_days(self.state(62), "stepstone", NOW), 3)

    def test_a_failed_portal_keeps_its_older_window(self):
        state = self.state(10)
        self.assertEqual(sweep.window_days(state, "linkedin", NOW), sweep.DEFAULT_DAYS)

    def test_window_is_capped(self):
        self.assertEqual(sweep.window_days(self.state(24 * 60), "stepstone", NOW), sweep.MAX_DAYS)

    def test_three_weeks_off_are_still_read(self):
        self.assertEqual(sweep.window_days(self.state(21 * 24), "stepstone", NOW), 22)

    def test_an_unconfirmed_sweep_does_not_move_the_window(self):
        # The session died after the sweep, before the results were stored.
        state = self.state(30)
        state["portals"]["stepstone"]["pending_success"] = (NOW - timedelta(hours=1)).isoformat()
        self.assertEqual(sweep.window_days(state, "stepstone", NOW), 2)

    def test_confirm_makes_the_pending_time_count(self):
        path = Path(tempfile.mkdtemp()) / "sweep_state.json"
        pending = (NOW - timedelta(hours=1)).isoformat()
        path.write_text(json.dumps({"portals": {
            "stepstone": {"last_success": (NOW - timedelta(hours=30)).isoformat(), "pending_success": pending},
            "linkedin": {"last_success": (NOW - timedelta(hours=30)).isoformat()}}}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            sweep.confirm(path)
        state = json.loads(path.read_text(encoding="utf-8"))["portals"]
        self.assertEqual(state["stepstone"], {"last_success": pending})
        self.assertNotEqual(state["linkedin"]["last_success"], pending)
        self.assertEqual(sweep.window_days({"portals": state}, "stepstone", NOW), 1)

    def test_override(self):
        self.assertEqual(sweep.window_days(self.state(10), "stepstone", NOW, override=5), 5)

    def test_in_window(self):
        cutoff = NOW - timedelta(days=2)
        self.assertTrue(sweep.in_window(None, cutoff))
        self.assertTrue(sweep.in_window("2026-10-26T01:00:00Z", cutoff))
        self.assertTrue(sweep.in_window("2026-10-24", cutoff))  # a bare date means the whole day
        self.assertFalse(sweep.in_window("2026-10-20", cutoff))


def history():
    """The user's own record: every posting ever rated, and the tracked roles.
    Empty on a fresh checkout, so the history tests below skip until there is one."""
    path = REPO / "job_scraper" / "seen_jobs.json"
    seen = json.loads(path.read_text(encoding="utf-8")).get("seen", {}) if path.is_file() else {}
    tracker = REPO / "job_search_tracker.csv"
    rows = []
    if tracker.is_file():
        with tracker.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("role")]
    return [e for e in seen.values() if isinstance(e, dict)], rows


class ExampleProfile(unittest.TestCase):
    """Filters and weights of tools/sweep_profile.example.json, whatever the user's own profile says."""

    @classmethod
    def setUpClass(cls):
        cls.saved = sweep.PROFILE
        sweep.apply_profile(sweep.load_profile(sweep.PROFILE_EXAMPLE))

    @classmethod
    def tearDownClass(cls):
        sweep.apply_profile(cls.saved)


class Relevance(ExampleProfile):
    def test_keeps_software_data_and_ai_roles(self):
        for title in ["Senior Software Engineer (m/w/d)", "Softwareentwickler C# / .NET",
                      "Data Scientist", "KI-Entwickler (m/w/d)", "Founding Engineer",
                      "Team Lead Tech (m/f/d)", "Algo Trading Expert"]:
            self.assertTrue(sweep.is_relevant(title), title)

    def test_drops_obvious_non_fits(self):
        for title in ["Verkäufer Frischetheke (m/w/d)", "Berufskraftfahrer (w/m/d)",
                      "Werkstudent Softwareentwicklung", "Ausbildung Fachinformatiker",
                      "Masterarbeit Machine Learning"]:
            self.assertFalse(sweep.is_relevant(title), title)


class History(unittest.TestCase):
    """The user's own profile against the user's own record (skips without one)."""

    def setUp(self):
        self.seen, self.tracked = history()

    def good(self):
        return [e for e in self.seen if e.get("fit") in ("high", "medium") or e.get("status") == "ranked"]

    def test_never_drops_a_posting_that_was_ever_a_fit(self):
        if not self.good():
            self.skipTest("no rated postings yet")
        self.assertEqual([e["title"] for e in self.good() if not sweep.is_relevant(e.get("title"))], [])

    def test_every_past_fit_is_a_core_title(self):
        # Core titles get the fit check; a past fit landing in "edge" would only
        # get a title skim.
        if not self.good():
            self.skipTest("no rated postings yet")
        self.assertEqual([e["title"] for e in self.good() if sweep.tier(e.get("title")) != "core"], [])

    def test_never_drops_a_tracked_application(self):
        if not self.tracked:
            self.skipTest("no tracked applications yet")
        self.assertEqual([r["role"] for r in self.tracked if not sweep.is_relevant(r["role"])], [])

    def test_past_strong_fits_would_be_read_in_full_in_the_search_areas(self):
        # The title list still shows every posting; this pins that the score
        # puts what the user wanted above the automatic-read line.
        fits = [e for e in self.seen if e.get("fit") == "high" or (e.get("rank_score") or 0) >= 60]
        if len(fits) < 20:
            self.skipTest("fewer than 20 strong fits yet")
        below = [e["title"] for e in fits if sweep.score(e) < sweep.AUTO_READ["corridor"]]
        self.assertLessEqual(len(below), len(fits) // 20, below)


class Triage(ExampleProfile):
    def test_profile_roles_outscore_noise(self):
        strong = sweep.score({"title": "Senior Software Engineer C# / .NET (m/w/d)"})
        for title in ["SAP Berater (m/w/d)", "Call Center Agent (m/w/d)", "IT-Support Mitarbeiter",
                      "Innendienstmitarbeiter / Agenturassistent (m/w/d)", "Junior Frontend Developer"]:
            self.assertLess(sweep.score({"title": title}), strong - 15, title)

    def test_preferred_location_gets_its_bonus(self):
        base = {"title": "Softwareentwickler (m/w/d)"}
        self.assertEqual(sweep.score({**base, "location": "Potsdam"}), sweep.score(base))
        sweep.apply_profile({**sweep.PROFILE, "preferred_location": {"pattern": "potsdam", "bonus": 3}})
        try:
            self.assertEqual(sweep.score({**base, "location": "Potsdam"}), sweep.score(base) + 3)
        finally:
            sweep.apply_profile(sweep.load_profile(sweep.PROFILE_EXAMPLE))

    def test_copies_across_cities_collapse_to_one_line(self):
        rows = [{"title": f"Lead Architekt (m/w/d) in {c}", "company": "Acme Recruiting", "url": f"https://x/{c}",
                 "portal": "xing-search", "pass": "remote", "tier": "core", "score": 10}
                for c in ["Köln", "Berlin", "Frankfurt am Main"]]
        rows.append({"title": "Senior AI Engineer (all genders) in Berlin - Jobbird.com", "company": "Example Staffing",
                     "url": "https://y/1", "portal": "linkedin-search", "pass": "remote", "tier": "core",
                     "score": 19})
        out = sweep.collapse(rows)
        self.assertEqual(out[0]["copies"], 3)
        self.assertEqual([r.get("dup_of") for r in out[1:3]], ["https://x/Köln"] * 2)
        listed = sweep.title_list(out).splitlines()[1:]
        self.assertEqual(len(listed), 2)
        self.assertIn("x3", listed[0])

    def test_different_roles_of_one_company_stay_apart(self):
        rows = [{"title": t, "company": "Acme Space", "url": f"https://o/{i}", "portal": "freehire-search",
                 "pass": "corridor"} for i, t in enumerate(["Simulator Software Engineer (m/f/d)",
                                                             "Simulator Software Engineer / Architect (m/f/d)"])]
        self.assertFalse(any(r.get("dup_of") for r in sweep.collapse(rows)))


class Budget(ExampleProfile):
    def rows(self):
        return [{"title": "Senior Software Engineer", "url": f"https://x/{i}", "pass": "remote", "tier": "core",
                 "score": 20 + i} for i in range(5)] + [
                {"title": "Softwareentwickler", "url": "https://y/1", "pass": "corridor", "tier": "core", "score": 6}]

    def test_the_cap_keeps_area_roles_first_then_the_best_scores(self):
        out = sweep.cap_auto_read(self.rows(), 3)
        self.assertEqual([r["url"] for r in out if sweep.auto_read(r)], ["https://x/3", "https://x/4", "https://y/1"])

    def test_no_cap_reads_every_eligible_posting(self):
        self.assertEqual(sum(sweep.auto_read(r) for r in sweep.cap_auto_read(self.rows(), 0)), 6)

    def test_first_run_keeps_only_dated_postings_inside_the_window(self):
        rows = [{"portal": "xing-search", "date": None, "url": "a"},
                {"portal": "stepstone-search", "date": "2026-10-26T10:00:00Z", "url": "b"},
                {"portal": "instaffo-search", "date": "2025-03-12", "url": "c"}]
        fresh, old = sweep.baseline(rows, {"xing": 24, "stepstone": 24, "instaffo": 24}, NOW)
        self.assertEqual(([r["url"] for r in fresh], [r["url"] for r in old]), (["b"], ["a", "c"]))


class Watchlist(unittest.TestCase):
    def test_empty_by_default(self):
        self.assertIsNone(sweep.sweep_watchlist({}, NOW, log=lambda m: None))

    def test_runs_once_a_week(self):
        original = sweep.WATCHLIST
        sweep.WATCHLIST = {"X": ("https://x.invalid/", lambda body: [])}
        try:
            state = {"portals": {"watchlist": {"last_success": (NOW - timedelta(days=2)).isoformat()}}}
            self.assertIsNone(sweep.sweep_watchlist(state, NOW, log=lambda m: None))
        finally:
            sweep.WATCHLIST = original

    def test_a_broken_page_is_reported_not_hidden(self):
        original = sweep.WATCHLIST
        sweep.WATCHLIST = {"X": ("https://x.invalid/", lambda body: [])}
        sweep.fetch, real_fetch = (lambda url, timeout=40: "<html></html>"), sweep.fetch
        try:
            res = sweep.sweep_watchlist({}, NOW, log=lambda m: None)
        finally:
            sweep.WATCHLIST, sweep.fetch = original, real_fetch
        self.assertEqual(res["status"], "broken")
        self.assertIn("layout", res["searches"][0]["error"])


class EmployerBonus(unittest.TestCase):
    TABLE = ("| # | Employer | Fit | Name |\n|---|---|---|---|\n"
             "| 1 | x | Strong | [Muster Energie GmbH](https://example.org) |\n"
             "| 2 | x | Good | ABC / ABC Netz |\n"
             "| 3 | x | Moderate | Beispiel AG |\n")

    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(self.TABLE)
        self.saved = sweep.EMPLOYERS
        sweep.EMPLOYERS = sweep.load_employers(Path(fh.name))

    def tearDown(self):
        sweep.EMPLOYERS = self.saved

    def test_listed_employers_get_a_small_nudge(self):
        self.assertEqual(sweep.employer_bonus("Muster Energie GmbH"), 2)
        self.assertEqual(sweep.employer_bonus("ABC NETZ GmbH"), 2)
        self.assertEqual(sweep.employer_bonus("Beispiel AG"), 1)

    def test_generic_and_unlisted_names_get_nothing(self):
        for company in ["Holding Hansa GmbH", "Brewery Ltd", "Dewes GmbH", None]:
            self.assertEqual(sweep.employer_bonus(company), 0, company)

    def test_the_nudge_never_outweighs_the_role(self):
        self.assertLess(max(sweep.EMPLOYER_BONUS.values()), 5)

    def test_no_list_means_no_nudge(self):
        self.assertEqual(sweep.load_employers(REPO / "company_research" / "does-not-exist.md"), [])


class Area(ExampleProfile):
    def test_only_index_rows_are_checked(self):
        self.assertTrue(sweep.in_area({"pass": "corridor", "location": "München"}))
        self.assertFalse(sweep.in_area({"pass": "index", "location": "München", "title": "Dev"}))
        self.assertTrue(sweep.in_area({"pass": "index", "location": "Potsdam", "title": "Dev"}))
        self.assertTrue(sweep.in_area({"pass": "index", "location": "Hamburg", "title": "Dev (Remote)"}))


class Plan(ExampleProfile):
    def test_every_planned_portal_has_a_cli(self):
        for portal in sweep.PLAN:
            self.assertTrue((REPO / ".agents" / "skills" / f"{portal}-search" / "cli" / "src" / "cli.ts").is_file(), portal)

    def test_every_search_covers_the_corridor_or_remote(self):
        for portal, plan in sweep.PLAN.items():
            passes = {s["pass"] for s in plan["searches"]}
            self.assertTrue(passes <= {"corridor", "remote", "index"}, portal)

    def test_one_search_per_area_and_keyword(self):
        two = {**sweep.PROFILE, "areas": [{"name": "Berlin", "radius_km": 30}, {"name": "Leipzig", "radius_km": 20}]}
        plan = sweep.build_plan(two)
        self.assertEqual(len([s for s in plan["stepstone"]["searches"] if s["pass"] == "corridor"]), 2)
        self.assertEqual(len([s for s in plan["xing"]["searches"] if s["pass"] == "corridor"]),
                         2 * len(two["xing_keywords"]))
        self.assertIn(["-l", "Leipzig, Germany"], [s["args"] for s in plan["linkedin"]["searches"]])

    def test_remote_only_and_local_only(self):
        remote_only = sweep.build_plan({**sweep.PROFILE, "areas": [], "freehire_cities": []})
        self.assertTrue(all(s["pass"] in ("remote", "index") for p in remote_only.values() for s in p["searches"]))
        local_only = sweep.build_plan({**sweep.PROFILE, "remote": False})
        self.assertFalse(any(s["pass"] == "remote" for p in local_only.values() for s in p["searches"]))

    def test_no_occupational_fields_leaves_the_arbeitsagentur_out(self):
        self.assertNotIn("arbeitsagentur", sweep.build_plan({**sweep.PROFILE, "arbeitsagentur_fields": []}))


if __name__ == "__main__":
    unittest.main()
