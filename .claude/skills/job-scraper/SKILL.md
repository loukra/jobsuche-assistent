---
name: scrape
description: >
  Finds new job postings matching your profile via installed portal-search CLIs
  (LinkedIn, local job boards, and any skills added with /add-portal). Deduplicates
  across runs. Triggers on: job scrape, find jobs, search jobs, new jobs, job search,
  scrape jobs, /scrape
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(bun --version), Bash(bun run .agents/skills/*/cli/src/cli.ts *), Bash(python tools/job_key.py:*), Bash(python3 tools/job_key.py:*), Bash(python3 tools/salary_band.py:*), WebFetch, WebSearch, Agent, AskUserQuestion
---

# Job Scraper

---

## How It Works

This skill sweeps job portals with `tools/scrape_sweep.py`, which drives the
**installed portal-search CLIs** in `.agents/skills/` through a measured plan: every
posting since the last run in the user's search areas and, if wanted, fully remote in
Germany, paged to the end (WebSearch is the fallback for a broken portal). It
deduplicates against previously seen jobs and the application tracker, and presents
new matches with a quick fit assessment.

## Invocation

The user triggers this skill by saying things like:
- "Find new jobs"
- "Scrape for jobs"
- "Any new positions?"
- "/scrape"

Optional arguments:
- A focus area, e.g. "/scrape data science" or "/scrape geophysics"
- "broad" to run all search categories, e.g. "/scrape broad"
- "health" to run the portal health check only (Step 4.75), without searching, deduplicating, or presenting jobs - e.g. "/scrape health", or "/scrape health jobnet" to probe one portal even if disabled

---

## Execution Steps

### Step 0: Load State

1. Read `job_scraper/seen_jobs.json` (create if missing - start with `{"seen": {}}`)
2. Read `job_search_tracker.csv` to extract already-applied companies+roles
3. Read `search-queries.md` (this directory) for the location rules and the focus-area queries

### Step 1: Search

**The sweep is the search.** `tools/scrape_sweep.py` holds the measured plan for every enabled portal and builds the searches from the search profile `job_scraper/sweep_profile.json` (areas with radius, remote yes/no, keywords, title filters, weights; template and field guide in `tools/sweep_profile.example.json`): it searches every area and, if the profile says so, fully remote roles in Germany and pages every search until the portal runs out, over the window since that portal's last successful sweep. Never replace it with a few hand-picked keyword queries: reading page 1 of a keyword search is what lost postings on every portal (measured 2026-10-26: LinkedIn 10 of 552 postings per query in one area, StepStone and freehire capped at their page size, `--jobage 2` silently unfiltered on StepStone and the Arbeitsagentur).

**No search profile yet?** If `job_scraper/sweep_profile.json` is missing, the sweep stops with a message. Write it first as `/setup` describes (its search-profile step), from `CLAUDE.md`, `01-candidate-profile.md` and `search-queries.md`, show the user the areas, remote choice and keywords, and only then sweep.

A focus area ("/scrape data science") or "broad" does not narrow the sweep; it adds that category's keyword queries from `search-queries.md` on top (1b, last paragraph).

#### 1a. Check bun availability

```bash
bun --version
```

If this fails (bun not installed), skip to **1c (WebSearch fallback)** for all portals and note the fallback in the Step 5 output.

#### 1b. Run the sweep (primary)

```bash
python3 tools/scrape_sweep.py --out out
```

It runs one thread per portal (each portal's own requests stay sequential and paced; a twice-daily window takes roughly 15-20 minutes, a 3-day window about 35, most of it LinkedIn and XING), so run it in the background and wait for it: a foreground tool call stops at 10 minutes. It honours the `enabled` toggle (a portal whose `SKILL.md` frontmatter sets `enabled: false` is skipped and listed in the report; record it for the Step 5 summary) and writes:

- `out/sweep_candidates.json` - postings not yet in `seen_jobs.json`, `job_scraper/seen_index.tsv` or the tracker whose title passes the relevance filter. **These are this run's pool for Steps 2-5**, each tagged with `portal`, `pass` (`corridor`, `remote` or `index`), `tier` (`core`: software, data, AI, architecture, research near the physics background, every past fit is one; `edge`: passed only the wide filter, site managers, technicians, clerks mostly), a profile `score`, and `dup_of` on copies of the same role in another city or board (the first copy carries `copies`).
- `out/sweep_titles.txt` - the core titles of the pool as one line per role, for Step 3: index, `AUTO` mark, triage points (`pts`: a sum of title signals such as .NET +12, SAP -15, for ordering only, not `/rank`'s 0-100 score), area, portal, title, company, location, copy count. Corridor first, then remote, each by points. `out/sweep_titles_edge.txt` lists the edge titles the same way.
- `out/sweep_skipped.json` - new postings the title filter rules out (retail, trades, apprenticeships, theses), already shaped as Step 4 entries with `status: "skipped"`. Record them in the index in Step 4, unread.
- `out/sweep_report.json` - per portal: status (`ok`, `partial`, `broken`), the window in days, and per search the pages read, results, the portal's own total, how it ended (`empty page`, `portal total reached`, `no new results`, `capped`, `error`) and the verbatim error. Step 4.75 reads its verdicts from here.

The relevance filter only reads titles and is deliberately generous; `tests/test_scrape_sweep.py` checks that it never drops a posting that was ever rated high/medium, ranked, or applied to. The `remote` pass relies on each portal's own remote filter, which leaks hybrid roles: Step 3 still verifies remote in the posting text.

The window comes from `job_scraper/sweep_state.json` (last confirmed sweep per portal, plus 6 hours; 3 days for a portal never swept; at most 30). So a run after a few days off reaches back over all of them by itself. The sweep only writes its own time there as `pending_success`; it becomes the new start when Step 4 runs `--confirm` after storing everything. A session that dies before that leaves the old window in place, and the next run reads the same postings again (dedup drops what was stored). A failed portal never gets a pending time. Past 14 days the report lists the portal under `long_window`: StepStone and the Arbeitsagentur then read every posting of any age (their day filters stop at 14 and 28), which is slow, and more LinkedIn remote searches cap; say so in the Step 5 summary. Pass `--no-state` when measuring rather than scraping, `--days N` to force a window, `--portals a,b` to run a subset.

**Focus area or "broad":** after the sweep, also run that category's keyword queries from `search-queries.md` through the portal CLIs (each portal's `SKILL.md` documents its flags; never guess flags, the CLIs reject unknown ones), with `--format json`, paging each query until a page brings nothing new. Scope them to the last 14 days with the portal's recency flag, read from its `SKILL.md` (StepStone and the Arbeitsagentur honour only a few day counts and round others up). A portal with **no recency flag** still gets scoped: every portal's search output carries a `date` field, so filter client-side and drop older results; never invent a flag. `--order PublicationDate` is a sort, and a sort is not a filter. Pool those results with the candidates and dedup them with `python3 tools/seen_jobs.py filter`. Portals added later via `/add-portal` are not in the sweep's plan until a measured entry is added to `PLAN` in `tools/scrape_sweep.py`; until then run them this way on every run and say so in the Step 5 summary.

If the sweep itself fails (a Python error rather than a portal error), fall back to running the portal CLIs by hand as in the paragraph above, for the corridor and remote searches of `search-queries.md`, and report the failure.

#### 1c. WebSearch fallback

Use `WebSearch` for:
- Portals listed in `search-queries.md` that do **not** have a corresponding directory under `.agents/skills/`
- Any portal the sweep reports as `broken` (every search failed), and the failed searches of a `partial` one
- When bun is unavailable (Step 1a failed)

Use the site-specific query strings from `search-queries.md` directly as WebSearch queries for these portals.

Tag each fallback result as WebSearch-sourced, keeping the portal tag when the fallback stands in for an installed portal whose CLI failed. Step 4 persists this as the entry's `source`, and Step 5 reports which portals ran on the fallback this run.

### Step 2: Fetch & Parse

For each promising result from Step 1:

**From CLI results:** Search output already includes title, company, location, date,
and URL. For jobs worth a deeper look, fetch full detail with that portal's `detail`
command (see its SKILL.md — do not guess flags) to extract **key requirements**,
**application deadline**, and a brief description snippet.

**Closed-at-source detection:** `linkedin-search detail` also returns `isActive`.
`false` means the posting page itself renders LinkedIn's "No longer accepting
applications" banner — the job died between being indexed and being fetched (expired
LinkedIn URLs redirect to *similar live jobs*, so a search hit can be a ghost). Mark
such a job, never silently drop it: write its entry to `seen_jobs.json` in Step 4 with
`"status": "expired"` and leave it out of the Step 5 presentation — an absent entry
looks identical to a job never seen, and the recorded status is what makes a later
ghost report self-triaging. `isActive: true` is only the absence of that banner, not
proof the posting is open; deadlines and dead URLs remain `/rank`'s job.

**From WebSearch results:** Use `WebFetch` on the posting URL and extract the same
fields manually. If it returns HTTP 403, retry with browser headers via curl per
`.claude/skills/job-application-assistant/09-web-research.md` before giving up — most
bank and corporate sites reject WebFetch's user agent while serving browsers normally.

**Store a URL that actually resolves to the posting.** A listing-page URL with a
`#fragment` appended (`.../jobs/ciso/#ikerian`) is not a posting: it fetches fine and
returns unrelated job titles, which makes every later `/rank` and `/apply` run fail on
that entry. When WebSearch only yields a listing page, search the employer's own careers
site for the role and store that URL instead, or drop the candidate rather than saving a
fragment link.

Candidates from the sweep are already deduplicated by these rules (it runs
`tools/seen_jobs.py filter`); apply them to focus-area and fallback results.

For every candidate:
- Skip if the URL matches any existing `seen_jobs.json` entry, regardless of
  that entry's key. This preserves dedup continuity for postings stored under
  the pre-helper key rule while new entries use the canonical key from Step 4.
- Otherwise, skip if the company+title combo already exists in `seen_jobs.json`
- Skip if the company+role already appears in `job_search_tracker.csv`

### Step 2.5: Mass-Posting Detection (within this run)

A distribution pattern worth flagging to the user as a caution signal, not as an accusation against the employer - it describes how a listing is being distributed, not a verdict on whether the company is legitimate. It alone proves nothing is wrong (companies do legitimately hire the same role across several cities); flag it so the user can factor it in when deciding whether to invest time, don't downgrade fit or silently exclude the result because of it.

If two or more results in this run's pool (from the same company, or sharing the same req/job ID visible in the URL or title) have substantially the same description and differ only in city/location/title, don't present them as separate rows. Consolidate into a single row and note the spread, e.g. "posted identically across 6 cities (BR, MX, GT)".

### Step 3: Quick Fit Assessment

**Which postings get read (sweep runs).** A day's sweep holds hundreds of relevant titles; reading every posting is neither possible nor needed, but every title gets looked at:

1. **Read in full automatically:** `python3 tools/sweep_review.py detail --out out --auto --sample 10` fetches every `AUTO` line of `sweep_titles.txt` (core titles from score 5 in the corridor, from 11 remote, which is a plain "Senior Software Engineer"; `tests/test_scrape_sweep.py` keeps 95% of past strong fits above the corridor line) into `out/details.json`. Each entry carries the posting text, a `remote` verdict (`hybrid` = the text names weekly office days, `remote`, or `unclear` with the hybrid wording it found), `contract` (freelance or hourly), any salary figures and `pay`: the salary band read by `tools/salary_band.py` with the figure to state (Step 5). Run it in the background when it has more than ~150 postings to fetch.
2. **Look at every other title:** read `out/sweep_titles.txt` to the end and skim `out/sweep_titles_edge.txt`, and pick generously whatever might fit by title, whatever its score: the score orders, it does not decide. Fetch them with `detail --out out --pick <idx,idx-idx>`; it skips what is already fetched.
3. **Fit check every posting in `details.json`** from its text, as below. A remote-pass posting the tool calls `hybrid` is out unless the office is in the corridor; `unclear` is decided from the text, and still unclear means out (name notable ones in Step 5). Write one verdict per read posting to `out/verdicts.json` (the shape is in `tools/sweep_review.py`), including the low ones.

**The audit (`--sample 10`)** also reads 10 random core lines and 5 edge lines that neither the score nor the title pass chose. Give them verdicts like any other. A high or medium one among them is a posting the triage would have lost: `store` logs every run's sample to `job_scraper/triage_audit.jsonl`, names any miss, and Step 5 reports it. A miss means the weights in `SCORE` (or the title pass) need fixing: say which signal failed and propose the change.

Everything not read stays unread and is filed as a fingerprint in Step 4; the Step 5 summary states how many titles were looked at, how many read in full (auto, picked, sampled), and the audit result.

For each job read, do a rapid fit check (NOT the full evaluation from `04-job-evaluation.md` - just a quick signal):

- **High match**: Role directly involves your core skills
- **Medium match**: Role is adjacent to your experience
- **Low match**: Role requires significant skills you lack

**Location preference:** if `search-queries.md`'s Location Filter marks a preferred area, a job based there that sits on the edge between two match levels takes the higher one, and it is listed first within its level in Step 5. This is a nudge, never a filter - a job outside the preferred area keeps its own level.

**Language override:** before assigning a match level, check the posting against `04-job-evaluation.md`'s Language Gate (a required language you haven't declared at all in your CLAUDE.md Languages table). A required language that's entirely undeclared overrides skill fit: mark it **Low** regardless of how well the skills align, and name it in the highlight bullets so it isn't buried under an otherwise-good-looking match. A **declared** language at a requirement that reads higher than your declared level is *not* an override — score fit normally, but add a red-flag bullet under that job's highlights (Step 5) quoting the posting's requirement next to your declared level, so the gap is visible without being auto-downgraded.

### Step 4: Deduplicate & Store

1. Derive each entry's key with the helper, never by slugifying in the moment:

```bash
python3 tools/job_key.py --company "<company>" --title "<title>" --url "<url>"
```

It prints one line: the canonical key for that posting. The key must be a pure function of the posting, because two runs that slugify differently store the same job twice and defeat the dedup this step exists to provide. The helper also length-caps long titles and disambiguates the cap with a hash of the full slug, so a truncated title is stable across runs and two different long titles never collide. `python3 tools/job_key.py --audit` reports entries in an existing state file that predate this rule; it only reports, and never rewrites keys, since a rewritten key breaks the tracker's own company+role matching.

2. Add ALL fetched jobs (new and skipped), each in one of two places:
   - **Postings no fit check read** - the sweep's `out/sweep_skipped.json` and any candidate you only judged by its title - go to the seen index with `python3 tools/seen_jobs.py index --in <file>`. It keeps a fingerprint per posting (date, portal, URL hash, company+title hash) in `job_scraper/seen_index.tsv` and drops fingerprints older than 90 days. The sweep reads thousands of these a day; as full entries they grew `seen_jobs.json` by megabytes per run.
   - **Every posting you read** (any fit, any status, including the low ones you skipped after reading) goes to `seen_jobs.json` with `python3 tools/seen_jobs.py add --in <file>`, in this structure:
```json
{
  "seen": {
    "<key from tools/job_key.py>": {
      "title": "...",
      "company": "...",
      "url": "...",
      "first_seen": "YYYY-MM-DD",
      "posted_date": "YYYY-MM-DD" | null,
      "deadline": "YYYY-MM-DD" | null,
      "fit": "high/medium/low",
      "status": "new/skipped/ranked/expired",
      "portal": "<source portal skill, e.g. jobindex-search>",
      "source": "cli/websearch"
    }
  }
}
```

The `portal` field records which CLI skill produced the job (results are already tagged per portal in Step 1b - persist that tag here). Entries written before this field existed lack it; the health check (Step 4.75) attributes those by matching the URL's domain against each portal's base URL, so do not backfill.

The `source` field records which mechanism produced the entry: `cli` for Step 1b portal-CLI output, `websearch` for the Step 1c fallback. This is what keeps a ghost-job report diagnosable after the run's summary is gone: a stored entry whose URL later resolves to nothing (or to a different job) reads very differently depending on whether it came from live CLI output or from a search index that can be weeks stale - and a presented job with no entry here at all points at fabrication, which Rule 1 forbids. Entries written before this field existed lack it; never backfill it - the mechanism was not recorded.

`/rank` extends this schema additively: ranked entries also carry `rank_score` (0–100 overall score), `rank_verdict` (fit band, e.g. "strong fit"), `rank_date` (ISO date of ranking), the veto fields `location_verdict` and `language_gate` (both PASS/FAIL/FLAG) with `language_note` (the quoted requirement explaining a non-PASS), and `strengths`/`gaps` (1-3 verbatim bullets each, copied from the scoring agent's findings). The `status` field is set to `"ranked"`. Do not drop any of these fields when re-writing entries. Entries ranked before `strengths`/`gaps` existed simply lack them; readers tolerate their absence and never backfill by guessing. Entries ranked before the verdict rename may carry a legacy PASS/FAIL/FLAG string in `location` - read that as the verdict when `location_verdict` is absent; in fresh entries `location` is always a place, never a verdict.

Read postings that name pay also carry `salary_band` (`{min, max, period, quote}` for a band, or `{min|max|fix, quote}` for a single figure), `salary_wish` (the figure to state, `null` without a band or when the band ends below the floor) and `salary_label` (the Step 5 cell). `store` writes them from `details.json`; a posting without pay figures has none of the three.

`deadline` is a base field rather than a `/rank` extension: Step 2's detail fetch already extracts the application deadline, so it is written when the job is first seen and refreshed by `/rank` Step 4 when a scoring agent returns a different value. `null` means the posting states no deadline; a missing key means the entry predates this field - **never infer a deadline** from either, and never backfill by guessing.

`posted_date` is the posting's own publication date, taken from the `date` field Step 2's contract already guarantees on every portal CLI's search output. Step 1b uses that date to scope the run to the last 14 days and then drops it, so nothing downstream can distinguish a posting published yesterday from one published two years ago - `first_seen` is when this scraper first saw the entry, not when the employer posted it. Persisting it makes Step 1b's window auditable after the run and gives `/rank` a freshness signal to weigh, instead of rediscovering the date and recording it in prose that nothing reads. That gap landed for real: a freehire-search posting dated 2024-05-13 was scraped and ranked Strong Fit at position 1 of 133, its own scoring note observing the listing "may be long stale" with nothing able to act on it. `null` means the portal returned no date for that result (the CLIs emit `date: null` when a listing omits it); a missing key means the entry predates this field - **never infer a posting date** from either, and never backfill by guessing.

3. Only present jobs NOT already in the seen list (matched by URL or
   company+title) or tracker.

4. **Sweep runs file all of the above in one call**, after Step 3's verdicts are written:

```bash
python3 tools/sweep_review.py store --out out --verdicts out/verdicts.json
```

It adds every posting with a verdict to `seen_jobs.json`, files everything else (unread candidates, copies, `sweep_skipped.json`) in the index, and then confirms the sweep (`scrape_sweep.py --confirm`), so the next run starts from this one. It refuses to run while a posting in `details.json` has no verdict. Never confirm before storing: an unconfirmed sweep is what lets the next run recover from a session that died halfway. Results of focus-area queries outside the sweep can go into the same `verdicts.json` with their full entry fields.

### Step 4.5: Generate Referral Contact Links (High & Medium Fit Only)

For every job from this run with `fit` of **high** or **medium** (skip low-fit jobs),
build two LinkedIn people-search URLs so the user can find a recruiter or team member to
reach out to for a referral or a warm intro. This is deliberately a link-generation step,
not an automated lookup: no scraping, no third-party API, zero runtime dependencies or
credentials required.

**A. Recruiters / Talent Acquisition (the referral path)**
```
https://www.linkedin.com/search/results/people/?keywords=<url-encoded "<Company Name> recruiter">&origin=GLOBAL_SEARCH_HEADER
```

**B. Role/team peers (informational-outreach / warm-intro path)**
```
https://www.linkedin.com/search/results/people/?keywords=<url-encoded "<Company Name> <role keyword>">&origin=GLOBAL_SEARCH_HEADER
```
Use a short keyword drawn from the posting's title for `<role keyword>` - e.g. a posting
titled "AI Program Manager" becomes `"<Company Name> AI Program Manager"`.

Both links are for the user to open and browse themselves - never fetch or scrape the
LinkedIn people-search result pages programmatically. Never fabricate contacts or claim a
specific person was found; these are search links, not results.

### Step 4.75: Portal Health Check

Scraper-based portal CLIs rot silently: when a portal changes its markup, the parser usually exits 0 with zero results or with null/garbled fields, and the Step 1c fallback never fires because it only triggers on hard failure. This step catches that from evidence the run already holds.

**Free pass (no extra requests).** For each enabled portal that ran in Step 1b:

- **Sweep verdict:** `out/sweep_report.json` already says, per search, how it ended. `error` (with the verbatim message) or `capped` (the search hit its page cap before the portal ran out: postings may be missing) makes the portal suspect; report the message, never a guessed cause. A portal whose every search ended in `error` is `broken` there.

- **Degraded scan:** inspect the results it returned this run. Flags: `company` null or empty on every result, empty titles, undecoded entities (`&amp;`) or HTML fragments in titles, URLs that do not point at the portal. Any of these means the parser is half-working and `/scrape` is silently collecting junk.
- **Yield history:** if the portal returned zero results across all of this run's searches (the report's `results`, not just the new candidates), check whether `seen_jobs.json` holds prior entries from it (via the `portal` field, or by matching URL domains for entries predating the field) or `job_scraper/seen_index.tsv` has rows for it (second column). A portal that produced jobs on earlier runs and produces nothing now is suspect - the same queries worked before.

**Escalation (bounded, on suspicion only).** A suspect portal gets **one** sentinel probe: run its documented `search` with the example query from its own SKILL.md (that query provably worked when the skill was registered), the portal's limit flag capped at 3, `--format json`. If that returns nothing, retry **once** with a single common word. Only then is the verdict **broken**. A 429 or block page is **never** evidence of breakage - record the portal as **inconclusive (rate-limited)**, back off, and do not retry.

**Verdicts.** Healthy portals get silence - no table, no line. Anything else surfaces in the Step 5 summary as a health line.

**Probe-only mode (`/scrape health`).** Skip Steps 1-4 and this step's free pass (there is no fresh run to scan); instead probe every installed portal directly - enabled ones by default, a disabled one only when named explicitly (e.g. `/scrape health jobnet`). Each portal gets the sentinel probe above, the degraded criteria applied to whatever it returns, and - since the user explicitly asked for diagnosis - one `detail` fetch on the first result of each healthy portal (description must be readable decoded text; a failure downgrades to degraded). Report all statuses in this mode, including healthy. Volume stays bounded: one search, at most one retry, at most one detail per portal.

### Step 5: Present Results

Present new jobs in a table sorted by fit (high first), and within each fit level jobs in the preferred area from Step 3's location preference first. When Step 1b skipped
portals (`enabled: false`), report them with the `skipped (disabled):` line below
so opting one out stays visible rather than silent; omit the line when nothing
was skipped. When any portal's results came from the Step 1c fallback this run
(bun unavailable, or its CLI failed at runtime), report it with the
`fallback (websearch):` line - fallback results come from a search index that
can be stale, so the reader should know which rows carry that caveat; omit the
line when every portal ran its CLI. When Step 4.75 found a portal degraded, broken, or inconclusive,
add one `health:` line per suspect portal (healthy portals get no line); after
the report, offer to set that portal's `enabled: false` so `/scrape` stops
running it (and covers it via the Step 1c fallback) until it is fixed - only
edit the toggle with the user's confirmation, and never edit anything else in
the skill.

```
## New Job Matches - YYYY-MM-DD

Found X new positions (Y high, Z medium, W low match).

skipped (disabled): <portal-name>, <portal-name>

fallback (websearch): <portal-name>, <portal-name>

health: <portal-name> - degraded (company null on all 12 results); parsing anchors in .agents/skills/<portal-name>/url-reference.md
health: <portal-name> - broken (0 results for the SKILL.md test query and a broader retry); parsing anchors in .agents/skills/<portal-name>/url-reference.md

| # | Fit | Title | Company | Location | Gehalt | Deadline | URL |
|---|-----|-------|---------|----------|--------|----------|-----|
| 1 | High | ... | ... | ... | 65k–85k → 79k | ... | [Link](...) |

The **Gehalt** cell is the posting's `pay.label` from `details.json`, for high and medium rows (low rows leave it empty): `65k–85k → 79k` is the band and the Gehaltswunsch to state for it, `55k–70k ⚠ unter 75k` a band that ends below the floor (`salary_floor` in the search profile), `bis 85k` / `ab 70k` / `100k genannt` a single figure without a suggestion, an empty cell no pay in the text. The band a portal shows in its UI rather than the text wins over the text: LinkedIn's "Base pay range" (from `detail`, given by the employer), StepStone's salary payload, XING's teaser facts, Workwise, freehire and the Arbeitsagentur (search fields the sweep keeps as `portal_salary`). A portal's own estimate is marked in the cell: `(StepStone-Schätzung)` for StepStone's predicted range (every StepStone card checked on 2026-10-29 was one), `(XING-Schätzung)` for XING's Gehaltsprognose; an unmarked band is the employer's. An estimate is the market for the role, not the employer's budget: say so when the figure comes from one. For a posting outside `details.json` (focus-area or WebSearch results), run `python3 tools/salary_band.py --file <posting text>`. When `CLAUDE.md` names a different floor for a kind of employer, rerun it with `--floor <that figure>` and show that figure. The suggestion sits 70% of the way up the band, never above its top: a figure above the band is what gets an application dropped at screening. Never invent a band the text does not state.

If Step 2.5 flagged a mass-posting pattern, note it in the Title cell (e.g. "Frontend Developer (posted in 6 cities)") rather than burying it. Do the same for a declared-language-insufficient-level flag from the Language Gate (e.g. "Backend Engineer ⚠ fluent English required") - both are signals the user should see at a glance, not just in the detail highlights below.

### High-Match Highlights
For each high-match job, add 2-3 bullet points:
- Why it matches your profile
- Key requirements to check
- Any red flags (including mass-posting signals from Step 2.5)

### Contacts
For each high/medium-fit job from Step 4.5, add a short contacts block with the two
LinkedIn search links:
- Recruiters/TA search link, for the referral path
- Role/team-peer search link, for the warm-intro / informational-outreach path
```

After presenting, ask:
> "Want me to evaluate any of these in detail? Just give me the number(s)."

If the user picks a number, invoke the **job-application-assistant** skill workflow (fit evaluation first, then CV + cover letter if approved).

If the run found many new jobs (roughly 8+), also suggest `/rank` - it batch-scores all new postings against the full fit framework and returns a ranked shortlist, which beats eyeballing a long table. (`/rank` sets the `ranked` and `expired` status values in `seen_jobs.json`; treat both as already-seen for dedup purposes.)

### Step 6: Update Tracker (Optional)

If the user decides to apply to any job, the tracker row is written by **job-application-assistant Step 3b**, which Step 5 already routes into - do not add a second row here. Only when the user says they applied to something outside that path, add a row using the header and the match-then-update rule in `/outcome` Step 1.

---

## Important Rules

1. **Never fabricate job postings.** Only present jobs from actual CLI search/detail output or WebSearch/WebFetch results.
2. **Respect deduplication.** Always check seen_jobs.json AND job_search_tracker.csv before presenting.
3. **Focus on configured geographic area.** Skip jobs that require relocation or are clearly outside commute range.
4. **Only open positions.** Skip postings with expired deadlines or those marked as closed.
5. **Be efficient with detail fetches.** Don't run `detail` or WebFetch on every search hit — pre-filter by title/snippet, then fetch only promising matches.
6. **Complete, not sampled.** The sweep pages every search to the end; never cut it down to page 1 or a few keywords to save time. Use WebSearch only for gaps the CLIs don't cover.
7. **No automated people lookups.** Referral contacts (Step 4.5) are LinkedIn search links only - never fetch or scrape LinkedIn people-search result pages programmatically.
8. **Health checks are bounded and honest.** Step 4.75 spends at most one probe, one retry, and (in `health` mode) one detail fetch per portal - a diagnosis, not a crawl. A rate-limit is never evidence of breakage. Health verdicts come only from observed CLI output; a portal that could not be tested is reported as inconclusive, never guessed. The `enabled` toggle is the only thing the health check may edit, and only with confirmation.
9. **Flag distribution patterns, never accuse.** The mass-posting signal (Step 2.5) describes how a listing is being distributed, not a claim that the employer is a scam. Never name a company as fraudulent or untrustworthy - present the observation and let the user decide.
