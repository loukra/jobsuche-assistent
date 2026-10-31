---
name: workwise-search
version: 1.0.0
description: >
  Use this skill to search for jobs on Workwise (workwise.io), a German job board
  focused on tech, engineering, business and student roles (Festanstellung,
  Werkstudent, Praktikum, Duales Studium, Ausbildung). Covers Germany — Berlin,
  Hamburg, München, Köln, Frankfurt, Stuttgart and the rest. Invoke for open
  positions, vacancies and hiring in Germany, or to look up a specific Workwise
  posting. Trigger phrases: Workwise, workwise.io, jobs in Germany, German job
  board, Stellenangebote, Stellenanzeigen, Jobsuche, Jobangebote, offene Stellen,
  freie Stellen, Werkstudentenstelle, Praktikum, Duales Studium, Festanstellung,
  bewerben, Job in Berlin/München/Köln.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/workwise-search/cli/src/cli.ts *)
---

# Workwise Search Skill

Search live job listings from **Workwise** (`workwise.io`), a German job board whose
postings skew toward tech, engineering and business roles, with strong coverage of
student-track positions (Werkstudent, Praktikum, Duales Studium, Ausbildung).

No authentication, no API key, and **zero runtime dependencies** — it runs with just `bun`.

## When to use this skill

- Search German job openings by keyword, city, or remote preference
- Filter to recently published postings (`--jobage`)
- Get the full German description, salary band, hours and required skills for a posting

## Commands

### Search job listings

```bash
bun run .agents/skills/workwise-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keywords (job title, skill, role). Recommended.
- `--location <text>` / `-l <text>` — a German city (`"Berlin"`, `"München"`, `"Köln"`) or an explicit `"lat,lon"` pair. See **Locations** below.
- `--radius <km>` — radius around `--location`. Default `30`.
- `--remote <mode>` — `remote` (only fully-remote postings) or `onsite`. There is no `hybrid` value; the portal's filter has no hybrid option.
- `--jobage <days>` — keep only postings published within N days. **Costs one extra request per result** — see **Dates** below.
- `--with-dates` — fill in each result's publication date without filtering.
- `--page <n>` — page number (1-indexed, 25 results per page).
- `--limit <n>` / `-n <n>` — cap results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/workwise-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the numeric job ID from `search` results (e.g. `123632`). A full
`workwise.io/job/...` URL works too. Returns the full description, publication date,
validity date, employment type, hours, salary band, required skills and status.

## Usage examples

```bash
# Data engineering roles anywhere in Germany
bun run .agents/skills/workwise-search/cli/src/cli.ts search -q "Data Engineer" --format table

# Software developers within 30 km of Berlin
bun run .agents/skills/workwise-search/cli/src/cli.ts search -q "Softwareentwickler" -l "Berlin" --radius 30 --format table

# Working-student roles in Munich
bun run .agents/skills/workwise-search/cli/src/cli.ts search -q "Werkstudent Informatik" -l "München" --limit 10 --format table

# Fully-remote DevOps roles published in the last 30 days
bun run .agents/skills/workwise-search/cli/src/cli.ts search -q "DevOps" --remote remote --jobage 30 --format table

# Second page of controlling roles in Hamburg
bun run .agents/skills/workwise-search/cli/src/cli.ts search -q "Controlling" -l "Hamburg" --page 2 --format json

# Full details for a specific posting
bun run .agents/skills/workwise-search/cli/src/cli.ts detail 123632 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Locations

The portal's location filter needs coordinates, which its own site gets from Google
Places using a key we cannot use. Rather than take on a geocoder dependency, the CLI
ships coordinates for ~90 German cities and accepts raw coordinates for anywhere else:

- **A known city:** `-l "Berlin"`, `-l "München"` (or `"Muenchen"` / `"munich"` — matching is case- and umlaut-tolerant).
- **Anywhere else:** `-l "51.2277,6.7734"` — a `lat,lon` pair, e.g. from any map.

An unrecognised city exits `1` with code `UNKNOWN_LOCATION` and lists the known names,
rather than silently returning nationwide results.

**A location search returns jobs *at* that location plus jobs with no fixed location.**
That is the portal's behaviour, not a bug in the filter. Searching Berlin returns
Berlin-based postings (roughly a third of a typical page), plus two kinds of
`location: null` posting — fully-remote roles, and travelling roles (Montage, site work)
that carry no location while still reporting `remoteWork: not_possible`. It also returns
remote-friendly postings headquartered in other cities.

`--remote onsite` narrows to postings tied to the location, which is usually what you
want for a commute-constrained search. Verified: Berlin + `--remote onsite` → 6 results,
all Berlin.

## Dates

**The search API returns no publication date.** This is a portal limitation, not an
oversight — the endpoint that backs the site's own results list simply does not carry
one, and there is no server-side posting-age parameter either.

So `date` is `null` in plain `search` output, and the two date flags fill it in by
reading each posting's page:

- `--with-dates` — adds the date to every result.
- `--jobage <days>` — adds the date, then drops anything older (and anything whose date could not be read).

Both cost **one extra request per result**, so pair them with `--limit`. The CLI reads
only the head of each page and cancels the rest of the download, so a date costs about
10 KB rather than the 250 KB a full page fetch would.

## Notes

- Data comes from Workwise's own search service (`search.workwise.io`) — the same JSON API that backs the site's `/jobsuche` page. That page is client-rendered, so there is no server-rendered HTML to parse. No credentials, no cost.
- `robots.txt` places no `Disallow` on the `User-agent: *` group, so search and job pages are not excluded. Even so, this is an internal API rather than a documented public one: **keep volume low and treat it as personal use.**
- **Search is semantic, not keyword-matching.** The API tokenizes the query server-side into occupation categories, so `-q "Data Engineer"` returns roles it classifies as data engineering — including adjacent titles — rather than a literal title match. Result counts are correspondingly smaller and more precise than a keyword board's.
- Workwise is a mid-sized board. A national search for a niche role often returns tens of results, not thousands — a low count is usually the portal's real inventory, not a broken parser. **Outside the big metros this bites hard:** a 30 km `--remote onsite` search around a small town typically returns 1-3 postings. Widen `--radius` (40-60 km pulls neighbouring towns into range and reaches the nearest large city) or drop `--remote onsite` to include location-free roles.
- Job IDs are numeric (e.g. `123632`). `/job/<id>` redirects to the canonical `/job/<id>-<slug>`, so the slug is never required.
- Postings are in German; `detail` returns the German description verbatim.
