# /html-report - Generate Application Tracker Dashboard

Generate a self-contained HTML dashboard from `job_search_tracker.csv` and the application archives under `documents/applications/`. The output is a single `.html` file — no server, no dependencies — that can be opened directly in a browser.

**The page is built by `tools/html_report.py`, never by hand.** Steps 1–3 below are the specification that script implements (pinned by `tests/test_html_report.py`); read them to know what the dashboard contains, but do not reimplement them. The command is: parse the arguments (Step 0), run the script (see "How to run"), relay its summary (Step 4).

## Step 0: Parse Arguments

- No argument → output to `reports/application-dashboard.html`
- A path argument (e.g. `/html-report ~/Desktop/report.html`) → use that path
- `--open` flag → after writing, tell the user to open the file (cannot open a browser directly)

`reports/` is gitignored on purpose: the dashboard is a view of the tracker, regenerated on demand, never committed.

## How to run

```bash
python3 tools/html_report.py                      # -> reports/application-dashboard.html
python3 tools/html_report.py <path>               # -> that path
```

The script creates the output directory, writes the page and prints the summary for Step 4 (sent, drafted, per-status counts, funnel, rejection rate, plus any unrecognised status values and outcome files it could not match to a tracker row). If it fails, fix the cause (usually a malformed tracker row or an unreadable `outcome.md`) and rerun — do not fall back to writing the page yourself.

---

## Step 1: Collect Data

*(Specification of what `tools/html_report.py` does — not steps for the agent to perform.)*

Read in parallel:

1. **`job_search_tracker.csv`** — the primary source. Parse every row into a record with fields:
   `date`, `company`, `sector`, `role`, `role_type`, `channel`, `status`, `contact_person`, `fit_rating`, `notes`, `cv_file`, `cover_letter_file`, `source`, `deadline`

   Rows written before `deadline` existed have thirteen fields and no fourteenth value. Treat the missing field as empty - never drop the row, and never infer a deadline from its `date`.

2. **`documents/applications/*/outcome.md`** — for each resolved application, read the outcome file to get the exact interview stages reached (the checkboxes) and any notes. Merge this into the matching tracker row by company+role fuzzy match (lowercase, ignore punctuation). If an archive exists for a row but there is no match, attach it as extra context anyway.

Status normalisation — map tracker values to six canonical buckets before computing stats:
- `drafted` → **Drafted** (documents written by `/apply`, not yet submitted)
- `applied` → **Active** (resume submitted, no further signal)
- `interview` → **Interview**
- `offer` → **Offer**
- `hired` → **Hired**
- `rejected` / `no_response` / `no response` / `offer_declined` / `offer declined` / `withdrawn` → **Rejected/Closed**
- anything else → **Rejected/Closed**, and name the unrecognised value once in the status breakdown — matching is case-insensitive

   The bucket map tolerates the legacy space spellings on read so nothing written before
   the canonical forms were locked drops out of the stats; the **Tracker status vocabulary**
   in `/outcome` is the authoritative set.

---

## Step 2: Compute Summary Stats

*(Specification, implemented in `tools/html_report.py`.)*

From the normalised data compute:

**Drafted rows are excluded from every statistic below** — they were never submitted. Report the Drafted count on its own, and include it only in the status breakdown.

- **Total applications**
- **By status bucket:** count per bucket
- **By sector:** count per **sector group**, never per raw value. The tracker `sector` column is free text written per posting, so `sector_group()` in `tools/html_report.py` collapses it: an explicit `<Group>: <detail>` prefix (the convention `/apply` Step 6b writes) wins; otherwise the first keyword hit in `SECTOR_GROUPS` (Defence & Space, Healthcare, Research & Deep Tech, AI & Data Products, Energy, Industry & Measurement, Mobility & Automotive, Finance, Real Estate & Commerce, Media & Publishing, Public Sector & Education, Business Software & IT); otherwise Other; empty → "(not recorded)". The sector filter uses the same groups, the table shows the group with the raw value underneath, and the script summary lists every row that fell into Other so its tracker value can be prefixed (the raw values were "alles sehr detailliert", and the chart must always produce sensible groups)
- **By channel:** count per **channel label**, not per raw `channel` value. The commands only write `portal` / `online` / `referral`, so `channel_label()` in `tools/html_report.py` refines the generic values by the `source` URL host: known job boards by name (`JOB_BOARDS`: LinkedIn, XING, StepStone, JOIN, Indeed, Arbeitnow, freehire, Instaffo, Arbeitsagentur, ...), applicant-tracking hosts (`ATS_HOSTS`: Workday, softgarden, Greenhouse, Personio, ...) and any other domain under `online` as "Company site", an unknown board host as its bare domain. A channel value that names a platform (`instaffo`, `referral`, `email`) wins over the host. Without a usable source the raw value is shown capitalised. The table shows the label with the raw value underneath ("channel ... aufteilen in linkedin xing usw")
- **By year/season:** group by the `date` field (which may be a year like `2025` or a full date)
- **Funnel rates:** what % progressed past resume screen (reached Interview or beyond). Compute stage-reached from history, not current status: an application counts as having reached a stage when its current status implies it **or** its merged `outcome.md` stage checkboxes (Step 1.2) show the stage was reached - a `rejected` row whose outcome file ticks an interview stage reached Interview, and a `hired` row reached every stage before Hired. Current status alone structurally undercounts every earlier stage: a finished search would read as though nobody ever interviewed. **Interview rounds** (show how far each application got): the number of ticked interview checkboxes (Phone screen, Technical interview, Case interview, Final round), at least 1 once Interview is reached by status; the funnel shows them as Interview round 1, Interview round 2 and Interview round 3+ (round 1 = reached Interview), and the table's status cell names the round and the furthest ticked stage (e.g. `rejected · round 2: Technical interview`).
- **Quiet applications**: for every open, sent row (Active, Interview, Offer) the days since the last contact, counted like `/outcome` Step 1.3 from the row's `date` or the latest dated entry in `notes`, whichever is more recent. Rows quiet for **30+ days** are counted on their own card ("Quiet 30+ days") and highlighted in the table's Quiet column. In the status doughnut and on the Active card, quiet **Active** rows are shown as their own grey slice "Quiet 30+ days" (`#94a3b8`) instead of under Active - display only, the bucket, the status filter and every rate still treat them as Active. The status is never changed: closing a quiet row stays with `/outcome stale`.
- **Rejection rate:** true rejections (`rejected`, `no_response`) ÷ applications with a final outcome. `offer_declined` (the candidate turned the offer down - a success) and `withdrawn` (candidate-initiated) are not rejections and stay out of the numerator; Interview and Offer rows are still unresolved, so they stay out of the denominator along with Active. The Rejected/Closed status *bucket* still groups all closed rows for the doughnut - the rate just must not reuse the bucket blindly.

---

## Step 3: Generate the HTML

*(Specification, implemented in `tools/html_report.py`.)*

Write a single self-contained HTML file. All CSS is inline in a `<style>` block. All JS is inline in a `<script>` block. Draw the doughnut and bar charts as hand-generated inline SVG — no Chart.js, no CDN, no external dependencies of any kind. The report must render fully offline on every open.

**Escaping (required):** HTML-escape every CSV/outcome-file value (`&` `<` `>` `"` `'`) before interpolating it into the page — this includes table cells, `title` attributes on truncated notes, and any text placed inside SVG (`<text>` labels, chart tooltips). Notes and company names copied from job postings routinely contain these characters; unescaped, they break the layout or inject markup into a page the user opens routinely.

### Layout

```
┌─────────────────────────────────────────────┐
│  🔍 Job Search Dashboard    Generated: DATE  │
├──────┬──────┬──────┬──────┬──────┬───────────┤
│Sent  │Draft │Active│Inter-│Offer │Rejected/  │  ← stat cards
│  N   │  N   │  N   │view N│  N   │Closed   N │
├──────┴──────┴──────┴──────┴──────┴───────────┤
│  Status breakdown (doughnut) │ By sector (bar)│  ← charts row
├─────────────────────────────────────────────  ┤
│  By channel (bar)  │  Funnel (horizontal bar) │  ← charts row
├──────────────────────────────────────────────  ┤
│  Application flow (Sankey, full width)       │
├──────────────────────────────────────────────  ┤
│  Applications  [Status ▾] [Sector ▾] [🔍 ...]│  ← table with filters
│  date │ company │ sector │ role │ status │ ... │
│  ...                                          │
└───────────────────────────────────────────────┘
```

### Design spec

- **Colour palette:** CSS custom properties. Status colours:
  - Drafted: `#64748b` (slate)
  - Active: `#3b82f6` (blue)
  - Interview: `#f59e0b` (amber)
  - Offer: `#8b5cf6` (purple)
  - Hired: `#22c55e` (green)
  - Rejected/Closed: `#ef4444` (red)
- **Font:** system-ui stack, no web fonts
- **Stat cards:** white background, subtle shadow, large bold number, label below, left border in status colour. The Drafted card appears only when at least one row is drafted (most users submit on the day they draft, so it would usually read 0)
- **Charts:** contained in a 2-column grid on wide screens, stacked on narrow
- **Table:**
  - Alternating row shading
  - Status column uses a coloured pill/badge
  - `source` column renders as a hyperlink if the value is a URL (starts with `http`)
  - Empty cells render as `—`
  - Client-side filter: a text search input filters rows across company + role + sector; the status and sector dropdowns filter independently; all three combine (AND)
  - Rows are sorted newest-first by default (by `date` descending, then alphabetically by company)
- **Responsive:** usable at 900px+, not broken below that
- **Footer:** "Generated by Claude Code · ai-job-search · {ISO date}"

### Charts (inline SVG)

1. **Status doughnut** — slices for each status bucket, colours from the palette above
2. **By sector bar** (horizontal) — company count per sector, sorted descending
3. **By channel bar** — one bar per channel label from Step 2 (LinkedIn, StepStone, JOIN, Company site, Referral, ...)
4. **Application funnel** (horizontal bar) — Applied → Interview round 1 → Interview round 2 → Interview round 3+ → Offer → Hired, each bar = count reaching that stage, derived per Step 2's funnel rule (current status **plus** the merged `outcome.md` stage checkboxes), so a candidate who interviewed and was later rejected still counts in the Interview round 1 bar
5. **Application flow** (Sankey, full width) — Applied on the left; each stage splits into the next stage (Round 1, Round 2, Round 3+, Offer, Hired) and the applications that ended there, each end node named by the stage it left so two rejection nodes never read alike ("Waiting for reply", "Rejected at screening", "Rejected after round 1", "Open in round 2", "Offer pending", "Offer declined"; also No response, Withdrawn, Closed for an unrecognised status). Stage reached uses the same rule as the funnel, so the two charts never disagree; stages nobody reached get no column. Node height and band width are proportional to the count, the continuing stage sits on top of its column, and bands are ordered by target position so they do not cross. Drawn as inline SVG paths (cubic Béziers), no library

Build each chart as a hand-written `<svg>` element: compute bar lengths/doughnut arc angles from the stats in Step 2 and emit the `<rect>`/`<path>`/`<circle>` and `<text>` elements directly — no charting library, no `<canvas>`. Each `<svg>` has `role="img"` and an `aria-label` summarizing the chart (e.g. "Status breakdown: 3 Active, 2 Interview, 1 Offer"). Wrap each in a `<div class="chart-card">` with an `<h3>` title above. Remember to escape any label/value text drawn into `<text>` nodes per the escaping rule above.

### Table: columns to include

`Date` · `Deadline` · `Company` · `Role` · `Sector` · `Channel` · `Status` · `Quiet` (days since last contact, open rows only; 30+ highlighted) · `Notes` (truncated to 80 chars with `title` tooltip for full text) · `Source` (link or `—`)

Columns with only empty values across all rows may be omitted.

---

## Step 4: Write and Confirm

The script has already written the file. Present its summary in this shape:

> **Dashboard generated:** `<output path>`
>
> Open it in any browser — no server needed.
>
> **Summary:**
> - Applications sent: N · drafted, not yet sent: N
> - Active: N · Interview: N · Hired: N · Rejected/Closed: N
> - Funnel: N% progressed past resume screen
> - Rejection rate: N% (N of N resolved, N withdrawn)
>
> Re-run `/html-report` any time after adding new entries via `/apply` or `/outcome` to refresh the dashboard.

Mention unrecognised status values or unmatched outcome files when the script reports them — they usually mean a tracker row needs fixing with `/outcome`. Likewise relay "Sectors grouped as Other" and "Sector not recorded": the fix is prefixing that row's `sector` with a group (`<Group>: <detail>`), which `/apply` and `/outcome` do for new rows.

---

## Design Principles

- **Self-contained.** One file, fully offline — charts are inline SVG, no CDN or external requests of any kind.
- **Data-only.** This command reads and renders; it never writes to the tracker or archive.
- **Idempotent.** Re-running overwrites the previous report at the same path — no accumulation.
- **Graceful on sparse data.** With only a few rows (as now), charts render correctly for small N; the table is the primary value. Do not suppress charts just because N is small.
- **No fabrication.** Every number in the report comes directly from the CSV or outcome files. Do not infer or estimate missing fields.
