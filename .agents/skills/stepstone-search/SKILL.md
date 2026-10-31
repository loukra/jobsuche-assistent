---
name: stepstone-search
version: 1.0.0
description: >
  Use this skill to search live job listings on StepStone.de, one of Germany's
  largest commercial job boards, covering every sector and region (Berlin,
  Hamburg, München, Köln, Frankfurt, Düsseldorf, Stuttgart …)
  in German and English. Use it for any job search in Germany or a German city,
  and to look up the full text of a specific StepStone posting by its id or URL.
  Trigger phrases: StepStone, Stepstone Jobsuche, Stellenangebote, Stellensuche,
  Jobsuche, offene Stellen, Stellenanzeige, Vollzeit, Teilzeit, Werkstudent,
  Home-Office Jobs, Arbeit suchen, jobs in Germany, German job board, find a job
  in Berlin/Hamburg/München.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/stepstone-search/cli/src/cli.ts *)
---

# StepStone Search Skill

Search live job listings from **StepStone.de**, Germany's largest commercial job board.
No authentication, no API key, and **zero runtime dependencies** — it runs with just `bun`.

> This follows the repo's job-portal-skill pattern (see `linkedin-search` for the
> canonical country-agnostic example), scaffolded for the German market.

## Access and courtesy

`robots.txt` on `www.stepstone.de` permits the paths this skill uses — the `/jobs`
search endpoint and the `/stellenangebote--…-inline.html` posting pages. Its `Disallow`
rules cover legacy `/5/…` endpoints, `/m/`, `/mobile/`, `/public-api/`, and `/jobagent/`,
none of which the CLI touches. Requests carry an honest `stepstone-search-cli/1.0`
User-Agent rather than impersonating a browser.

It is still someone else's site: **keep volume low and use it for your own job search,
not for bulk collection.** The CLI backs off automatically on 429/5xx.

## When to use this skill

- Search for openings in a German city or region, optionally within a radius
- Filter by recency (`--jobage`) or home-office arrangement (`--remote`)
- Get the full description, employment type, and application deadline of a specific posting

## Commands

### Search job listings

```bash
bun run .agents/skills/stepstone-search/cli/src/cli.ts search [flags]
```

At least one of `--query` or `--location` is required.

Key flags:
- `--query <text>` / `-q <text>` — keywords: job title, skill, or company name.
- `--location <Ort>` / `-l <Ort>` — German city or region, e.g. `"Berlin"`, `"München"`, `"Nordrhein-Westfalen"`.
- `--radius <km>` — radius around the location (StepStone defaults to 30 km).
- `--jobage <days>` — posted within N days. The portal honours only `1`, `3`, `7` and `14`; other values are rounded **up** to the next of those (2 → 3), and above 14 there is no filter. `meta.jobageApplied` reports the bucket used.
- `--remote <mode>` — `remote` (nur Home-Office) or `hybrid` (teilweise Home-Office).
- `--page <n>` / `-p <n>` — page number (1-indexed, 25 results per page).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/stepstone-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts a bare posting id (`14438124`) or any StepStone posting URL.

## Examples

```bash
# Data engineering roles in Berlin from the last week, as a table
bun run .agents/skills/stepstone-search/cli/src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --format table

# Project management in Munich, widened to a 50 km radius
bun run .agents/skills/stepstone-search/cli/src/cli.ts search -q "Projektmanager" -l "München" --radius 50 --format table

# Fully remote DevOps roles nationwide, last two weeks
bun run .agents/skills/stepstone-search/cli/src/cli.ts search -q "DevOps" --remote remote --jobage 14 --limit 10 --format table

# Working-student positions in Hamburg, readable output
bun run .agents/skills/stepstone-search/cli/src/cli.ts search -q "Werkstudent Maschinenbau" -l "Hamburg" --format plain

# Second page of controlling roles across North Rhine-Westphalia
bun run .agents/skills/stepstone-search/cli/src/cli.ts search -q "Controlling" -l "Nordrhein-Westfalen" -p 2

# Full text of one posting
bun run .agents/skills/stepstone-search/cli/src/cli.ts detail 14438124 --format plain
```

## Output formats

| Format  | Use for                                                                 |
|---------|-------------------------------------------------------------------------|
| `json`  | Default. `{ "meta": { count, page, total }, "results": [...] }` — pipe into other tooling. |
| `table` | Scanning a result list in the terminal: id, title, company, location, date. |
| `plain` | Reading. For `detail`, prints the full description as flowing text.      |

Each search result carries `id`, `title`, `company`, `location`, `date`, `url`, and
`workFromHome`. Missing values are `null`, never omitted. `meta.total` is the total
number of matches StepStone reports for the query, which is usually far more than the
25 returned on one page.

Errors go to **stderr** as `{"error": "...", "code": "..."}` with exit code `1`.

## Notes

- **Dates are relative on the results page.** StepStone renders "vor 6 Tagen" / "Heute"
  rather than a timestamp, so `search` converts them to an ISO `YYYY-MM-DD` date. This
  is day-accurate, not exact. `detail` reads the true `datePosted` from the posting's
  JSON-LD, so prefer it when the precise date matters.
- **`--jobage` has four honoured values.** `ag=age_<days>` works for 1, 3, 7 and 14
  only; any other value is silently dropped and the search returns every posting
  regardless of age (measured 2026-10-26: age_2, age_4-6, age_10, age_21, age_28 and
  age_30 all gave the unfiltered total). The CLI therefore rounds up to the next
  honoured bucket; filter `date` client-side when the window must be exact.
- **Paging reaches the end.** `meta.total` is reliable and every page up to it is
  served (a 4,789-result search was read to its last page 192 on 2026-10-26).
- **CSS class names are build-hashed** (`res-xaz43y`, `res-kyg8or`) and change on every
  StepStone deploy. Every parser anchors on the stable `data-at="…"` attributes instead —
  if parsing ever breaks, that is the first thing to check. See `url-reference.md`.
- **The URL slug is decorative.** StepStone resolves a posting from its numeric id alone,
  so `detail` builds `…/stellenangebote--x--<id>-inline.html` and never needs the title slug.
- **`location` is often a list.** Many postings advertise several sites at once
  ("Karlsruhe, Köln, München, Hamburg …") — this is the portal's own field, not a parsing bug.
- **Pagination is 25 results per page.** Use `--page` to go deeper; `--limit` only caps
  what is emitted from the page already fetched.
