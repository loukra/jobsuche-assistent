"""Tests for tools/html_report.py (the /html-report generator)."""

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import html_report  # noqa: E402


def _repo(tmp_path):
    (tmp_path / "job_search_tracker.csv").write_text(textwrap.dedent("""\
        date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline
        2026-10-01,"Acme <b>&amp;</b> Co",Robotics,Engineer,Full-time,portal,rejected,,70,"notes with <script>alert(1)</script>",cv.pdf,cl.tex,https://example.com/job,
        2026-10-02,Beta GmbH,Energy,Developer,Full-time,online,applied,,,plain,cv.pdf,cl.tex,not-a-url
        2026-10-03,Gamma AG,Energy,Architect,Full-time,portal,drafted,,,,,,,
        2026-10-04,Delta,Robotics,Lead,Full-time,referral,withdrawn,,,,,,,
        2026-10-05,Epsilon,Robotics,Dev,Full-time,portal,on_hold,,,,,,,
        """), encoding="utf-8")
    app = tmp_path / "documents" / "applications" / "acme_engineer"
    app.mkdir(parents=True)
    (app / "outcome.md").write_text(textwrap.dedent("""\
        # Outcome: Acme <b>&amp;</b> Co — Engineer

        **Status:** rejected

        ## Interview stages reached
        - [x] Phone screen
        - [x] Technical interview
        - [ ] Case interview
        - [ ] Final round
        - [ ] Offer received
        """), encoding="utf-8")
    orphan = tmp_path / "documents" / "applications" / "zeta_role"
    orphan.mkdir()
    (orphan / "outcome.md").write_text("# Outcome: Zeta — Role\n\n- [ ] Phone screen\n", encoding="utf-8")
    return str(tmp_path)


def test_stats_follow_the_command_rules(tmp_path):
    _, stats = html_report.build(_repo(tmp_path), today="2026-10-12")
    assert stats["sent"] == 4            # drafted row excluded
    assert stats["drafted"] == 1
    assert stats["by_bucket"]["Active"] == 1
    assert stats["by_bucket"]["Rejected/Closed"] == 3   # rejected, withdrawn, on_hold
    assert stats["unrecognised"] == ["on_hold"]
    # 13-field rows survive and stay in the stats
    # channel refined by the source host: unknown host + "portal" -> bare domain,
    # non-URL source + "online" -> raw value, referral named, no source -> raw value
    assert stats["by_channel"] == {"example.com": 1, "Online": 1, "Referral": 1, "Portal": 1}
    # funnel from history: the rejected row ticked an interview stage
    assert stats["funnel"]["Interview round 1"] == 1
    assert stats["past_screen_pct"] == 25
    # rounds = ticked interview stages (phone screen + technical -> round 2)
    assert list(stats["funnel"]) == ["Applied", "Interview round 1", "Interview round 2", "Interview round 3+",
                                   "Offer", "Hired"]
    assert stats["funnel"]["Interview round 2"] == 1
    assert stats["funnel"]["Interview round 3+"] == 0
    # rejection rate: 1 true rejection / 2 resolved (withdrawn is resolved but not a
    # rejection; the unrecognised on_hold is not a known final outcome)
    assert stats["true_rejections"] == 1
    assert stats["resolved"] == 2
    assert stats["rejection_rate"] == 50
    assert stats["withdrawn"] == 1
    assert stats["unmatched"] == ["Zeta — Role"]


def test_page_escapes_values_and_is_self_contained(tmp_path):
    page, _ = html_report.build(_repo(tmp_path), today="2026-10-12")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "Acme &lt;b&gt;&amp;amp;&lt;/b&gt; Co" in page
    assert 'href="https://example.com/job"' in page
    assert "not-a-url" in page and 'href="not-a-url"' not in page
    assert "Generated: 2026-10-12" in page
    assert "<th>Deadline</th>" not in page      # column empty everywhere -> omitted
    assert "Zeta — Role" in page
    assert 'role="img"' in page and "<path " in page
    for external in ("http://", "cdn.", "<link "):
        assert external not in page.replace("https://example.com/job", "")
    assert "https://" not in page.replace("https://example.com/job", "")


def test_main_writes_file_and_summary(tmp_path, capsys):
    root = _repo(tmp_path)
    out = tmp_path / "reports" / "dash.html"
    assert html_report.main([str(out), "--root", root]) == 0
    assert out.exists() and out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    text = capsys.readouterr().out
    assert "Applications sent: 4 · drafted, not yet sent: 1" in text
    assert "Rejection rate: 50% (1 of 2 resolved, 1 withdrawn)" in text


def test_sector_group_collapses_free_text_sectors():
    g = html_report.sector_group
    assert g("Space & defence") == "Defence & Space"
    assert g("Defence electronics (Electronic Solutions division; Hamburg)") == "Defence & Space"
    assert g("Healthcare software (digital patient care)") == "Healthcare"
    assert g("eHealth / lokale KI für den Dokumenteneingang in Arztpraxen") == "Healthcare"
    assert g("Quantum technology research (Hamburg campus)") == "Research & Deep Tech"
    assert g("CarSharing / nachhaltige Mobilität") == "Mobility & Automotive"
    assert g("Immobilienbewertung / PropTech (Hypoport-Gruppe)") == "Finance, Real Estate & Commerce"
    assert g("SHK-Großhandel; E-Commerce / Online-Shop") == "Finance, Real Estate & Commerce"
    assert g("Software für Zeitungsverlage (White-Label-SaaS)") == "Media & Publishing"
    assert g("E-Mail-Management / Outlook-Add-in") == "Business Software & IT"
    assert g("Software für die Sozialwirtschaft, HR/Payroll, IT-Services") == "Business Software & IT"
    assert g("KI-Produkte für die Industrie") == "AI & Data Products"
    assert g("Energieversorger, Messtechnik") == "Energy, Industry & Measurement"
    assert g("Robotics") == "AI & Data Products"
    assert g("Zoo") == "Other"
    assert g("") == "(not recorded)"


def test_sector_group_short_keywords_match_whole_words_only():
    g = html_report.sector_group
    assert g("Fahrzeugbau") == "Mobility & Automotive"       # "hr" inside Fahrzeug must not fire
    assert g("Lehrmittel nach Jahr") == "Other"               # neither "hr" nor "it" inside words
    assert g("HR/Payroll") == "Business Software & IT"


def test_sector_group_prefix_wins_over_keywords():
    g = html_report.sector_group
    assert g("Healthcare: Software für Arztpraxen") == "Healthcare"
    assert g("Business Software & IT: Praxissoftware") == "Business Software & IT"   # keyword "praxis" loses
    assert g("defence: Sonar") == "Defence & Space"
    assert g("Mobility and Automotive: Rail") == "Mobility & Automotive"
    assert g("Other: Zoo") == "Other"
    assert g("AI") == "AI & Data Products"
    assert g("Not a group: but a colon in the detail text about health") == "Healthcare"


def test_chart_and_filter_use_sector_groups_table_keeps_detail(tmp_path):
    page, stats = html_report.build(_repo(tmp_path), today="2026-10-12")
    # Robotics x3 sent -> AI group, Energy x1 sent -> Energy group; drafted row excluded
    assert stats["by_sector"] == {"AI & Data Products": 3, "Energy, Industry & Measurement": 1}
    assert stats["other_sectors"] == []
    assert stats["unrecorded_sectors"] == []
    assert 'data-sector="AI &amp; Data Products"' in page
    assert '<option value="AI &amp; Data Products">AI &amp; Data Products</option>' in page
    assert "Robotics</div>" in page   # detail still visible in the table under the group


def test_rows_grouped_as_other_are_listed_for_fixing(tmp_path):
    (tmp_path / "job_search_tracker.csv").write_text(textwrap.dedent("""\
        date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline
        2026-10-01,Zoo AG,Tierpark,Dev,Full-time,portal,applied,,,,,,,
        2026-10-02,Blank GmbH,,Dev,Full-time,portal,applied,,,,,,,
        2026-10-03,Draft Co,Tierpark,Dev,Full-time,portal,drafted,,,,,,,
        """), encoding="utf-8")
    _, stats = html_report.build(str(tmp_path), today="2026-10-12")
    assert stats["by_sector"] == {"Other": 1, "(not recorded)": 1}
    assert stats["other_sectors"] == ["Zoo AG: Tierpark"]        # drafted rows are not reported
    assert stats["unrecorded_sectors"] == ["Blank GmbH"]


def test_channel_label_reads_the_board_off_the_source_host():
    c = lambda channel, source="": html_report.channel_label({"channel": channel, "source": source})
    assert c("portal", "https://www.linkedin.com/jobs/view/1") == "LinkedIn"
    assert c("portal", "https://de.linkedin.com/jobs/view/x") == "LinkedIn"
    assert c("portal", "https://www.xing.com/jobs/1") == "XING"
    assert c("portal", "https://www.stepstone.de/stellenangebote--x") == "StepStone"
    assert c("portal", "https://join.com/companies/x/1") == "JOIN"
    assert c("portal", "https://www.arbeitnow.com/view/x") == "Arbeitnow"
    assert c("online", "https://ag.wd3.myworkdayjobs.com/Acme/job/x") == "Company site"
    assert c("online", "https://hypoport.softgarden.io/job/1") == "Company site"
    assert c("online", "https://karriere.acme.example/jobs/1") == "Company site"
    assert c("online", "https://www.stepstone.de/x") == "StepStone"      # board wins over "online"
    assert c("instaffo", "https://de.linkedin.com/jobs/view/x") == "Instaffo"   # named channel wins
    assert c("referral") == "Referral"
    assert c("email") == "E-mail"
    assert c("portal", "https://jobs.example.org/1") == "example.org"
    assert c("portal") == "Portal"
    assert c("") == "Other"
    assert c("headhunter") == "Headhunter"


def test_table_shows_furthest_interview_round(tmp_path):
    page, _ = html_report.build(_repo(tmp_path), today="2026-10-12")
    assert "rejected · round 2: Technical interview" in page
    assert "applied · round" not in page          # no interview reached -> no round note


def test_quiet_days_flag_open_rows_without_touching_status(tmp_path):
    root = _repo(tmp_path)
    # Beta (applied 2026-10-02) is the only open sent row
    _, stats = html_report.build(root, today="2026-10-31")
    assert stats["quiet"] == []                     # 29 days
    page, stats = html_report.build(root, today="2026-11-01")
    assert stats["quiet"] == ["Beta GmbH"]          # 30 days
    assert stats["by_bucket"]["Active"] == 1        # status unchanged
    assert '<td class="nowrap quiet">30 d</td>' in page
    assert "Quiet 30+ days" in page
    # display only: the quiet Active row moves to its own doughnut slice
    assert stats["display_buckets"]["Active"] == 0
    assert stats["display_buckets"]["Quiet 30+ days"] == 1
    assert "Status breakdown: 1 Drafted, 1 Quiet 30+ days, 3 Rejected/Closed" in page


def test_quiet_days_count_from_latest_dated_note():
    row = {"bucket": "Active", "date": "2026-09-01", "notes": "applied (2026-09-01); followed up 2026-10-20"}
    assert html_report.days_quiet(row, "2026-10-25") == 5
    assert html_report.days_quiet(dict(row, bucket="Rejected/Closed"), "2026-10-25") is None
    assert html_report.days_quiet(dict(row, bucket="Drafted"), "2026-10-25") is None


def test_drafted_card_only_when_something_is_drafted(tmp_path):
    root = _repo(tmp_path)
    page, _ = html_report.build(root, today="2026-10-12")
    assert '<div class="lbl">Drafted</div>' in page
    tracker = tmp_path / "job_search_tracker.csv"
    tracker.write_text(tracker.read_text(encoding="utf-8").replace(",drafted,", ",applied,"), encoding="utf-8")
    page, _ = html_report.build(root, today="2026-10-12")
    assert '<div class="lbl">Drafted</div>' not in page


def test_flow_splits_each_stage_into_next_stage_and_endings(tmp_path):
    page, stats = html_report.build(_repo(tmp_path), today="2026-10-12")
    nodes = {n["id"]: (n["col"], n["count"]) for n in stats["flow"]["nodes"]}
    # drafted row excluded; empty stages (Round 3+, Offer, Hired) get no column
    assert nodes == {
        "Applied": (0, 4), "Round 1": (1, 1), "Round 2": (2, 1),
        "Applied|open": (1, 1), "Applied|withdrawn": (1, 1), "Applied|other": (1, 1),
        "Round 2|rejected": (3, 1),
    }
    links = {(a, b): n for a, b, n in stats["flow"]["links"]}
    assert links[("Applied", "Round 1")] == 1 and links[("Round 1", "Round 2")] == 1
    assert links[("Round 2", "Round 2|rejected")] == 1
    # flow is conserved: every application leaves Applied exactly once
    assert sum(n for (a, _), n in links.items() if a == "Applied") == stats["sent"]
    assert "<h3>Application flow</h3>" in page


def test_flow_offer_and_hired_paths():
    rows = [
        {"status": "hired", "bucket": "Hired", "outcome": None},
        {"status": "offer_declined", "bucket": "Rejected/Closed", "outcome": None},
        {"status": "offer", "bucket": "Offer", "outcome": None},
    ]
    assert html_report.flow_path(rows[0]) == (["Applied", "Round 1", "Offer", "Hired"], None)
    assert html_report.flow_path(rows[1]) == (["Applied", "Offer"], "offer_declined")
    assert html_report.flow_path(rows[2]) == (["Applied", "Round 1", "Offer"], "open")
