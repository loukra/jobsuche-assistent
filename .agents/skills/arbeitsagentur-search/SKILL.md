---
name: arbeitsagentur-search
version: 1.0.0
description: >
  Use this skill to search German job listings on the Bundesagentur für Arbeit
  JOBBÖRSE (arbeitsagentur.de/jobsuche) — Germany's largest public job board,
  covering employment, apprenticeships (Ausbildung), internships and
  self-employment across every sector and region. Use it for any job search in
  Germany or a German city (Berlin, Hamburg, München, Köln …),
  and to look up the full text of a specific Arbeitsagentur posting by its
  reference number. Trigger phrases: Arbeitsagentur, Jobbörse, Bundesagentur für
  Arbeit, Stellenangebote, Stellensuche, Jobsuche, offene Stellen, Stellenanzeige,
  Ausbildungsplatz, Praktikum, Arbeit suchen, jobs in Germany, German job board,
  find a job in Berlin/Hamburg/München.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts *)
---

# Arbeitsagentur Search Skill

Search live job listings from the **Bundesagentur für Arbeit JOBBÖRSE** — the German
federal employment agency's job board at `arbeitsagentur.de/jobsuche`. It is the largest
job database in Germany and includes postings that never reach the commercial boards
(public sector, Handwerk, Ausbildung, regional employers).

Runs on the portal's own public JSON API: **no account, no API key to obtain, no billing,
and zero runtime dependencies** — just `bun`.

## Access and courtesy

`robots.txt` on `www.arbeitsagentur.de` is `Allow: /`, and these are the same endpoints
the public search page calls from a browser, so no terms are being worked around. Still,
this is a public service funded by contributions: **keep volume low, use it for your own
job search, and don't bulk-collect.** The CLI backs off on 429/5xx automatically.

No credential is needed. The requests carry a fixed `X-API-Key: jobboerse-jobsuche`
header that is baked into the portal's public frontend config; the CLI ships it. If the
portal ever rotates it, the CLI's 403 message tells you where to re-read it, and
`ARBEITSAGENTUR_API_KEY` overrides the built-in value.

## When to use this skill

- Search job openings anywhere in Germany, by keyword, city, postcode, or radius
- Filter by recency, offer type (Arbeit / Ausbildung / Praktikum / Selbständigkeit), or
  working-time model
- Read the full description of a specific posting from its reference number

## Commands

### Search job listings

```bash
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search [flags]
```

Key flags (pass at least `--query` or `--location`):
- `--query <text>` / `-q <text>` — keywords: job title, skill, or role (the portal's *was*).
- `--location <text>` / `-l <text>` — city, postcode, or region (the portal's *wo*), e.g. `"Hamburg"`, `"20095"`, `"Bayern"`.
- `--radius <km>` / `-r <km>` — search radius around `--location`, e.g. `25`, `50`.
- `--jobage <days>` — published within N days. The portal honours only `1`, `7`, `14` and `28`; other values are rounded **up** (2 → 7), above 28 there is no filter. `meta.jobageApplied` reports the bucket used.
- `--field <names>` — occupational field(s), the portal's `berufsfeld` facet; join several with `;` for OR, e.g. `"Informatik;Softwareentwicklung und Programmierung"`. Counts as a search term on its own. With a location this lists **every** posting of those fields in the area, not just keyword matches.
- `--offer-type <type>` — `arbeit` (default on the portal), `ausbildung`, `praktikum`, `selbststaendigkeit`.
- `--worktime <mode>` — `vollzeit`, `teilzeit`, `schicht`, `minijob`. `homeoffice` is rejected: the API returns 0 results for it (measured 2026-10-26); read each result's `homeoffice` field ("Homeoffice möglich") instead.
- `--page <n>` — page number (1-indexed, 50 results per page).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts detail <refnr|url> [--format json|plain]
```

`refnr` is the reference number from `search` results (e.g. `13644-311617-S`). A full
`arbeitsagentur.de/jobsuche/jobdetail/...` URL works too. Returns the full description,
salary range where published, entry date, contract duration, and Homeoffice/temporary-agency flags.

## Usage examples

```bash
# Software developer roles in Hamburg
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search -q "Softwareentwickler" -l "Hamburg" --format table

# Data engineer roles in Berlin, posted in the last 7 days
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --format table

# Part-time nursing roles within 50 km of München
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search -q "Pflegefachkraft" -l "München" -r 50 --worktime teilzeit --format table

# Apprenticeships (Ausbildung) for mechatronics technicians in Hamburg
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search -q "Mechatroniker" -l "Hamburg" --offer-type ausbildung --limit 10

# Everything within 25 km of a postcode, regardless of title
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts search -l "20095" -r 25 --jobage 3 --format table

# Full details for a specific posting
bun run .agents/skills/arbeitsagentur-search/cli/src/cli.ts detail 13644-311617-S --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing reference numbers to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single posting's full description (`detail` command) |

JSON search output is `{ "meta": { "count", "page", "total" }, "results": [...] }`; each
result carries at least `id`, `title`, `company`, `location`, `date`, `url`, with unknown
values as `null`. All errors go to **stderr** as `{ "error": "...", "code": "..." }` with
exit code `1`.

## Notes

- **Postings are in German.** Search in German for best coverage (`Softwareentwickler`
  finds far more than `software developer`), though English titles do appear.
- **Reference numbers are not numeric** — they look like `13644-311617-S` or
  `12265-485869_JB5229683-S`. Pass them to `detail` as-is.
- `--jobage` maps to the portal's `veroeffentlichtseit`, which honours only 1, 7, 14 and 28 days; every other value is silently ignored by the API (measured 2026-10-26: 2, 3, 10, 21, 30 all gave the unfiltered total), so the CLI rounds up.
- The API has **no remote filter**. `homeoffice: true` means "Homeoffice möglich", not fully remote.
- `meta.total` is the portal's own hit count for the query, independent of `--limit`.
- Descriptions are stored as Markdown (`##` headings, `-` bullets); the CLI unescapes
  the backslash escapes so `C\#` reads as `C#`.
- **`&` is missing from some company names** (`Stellenwert GmbH   Co. KG`) — that is how
  the portal's own API serves them, not a parsing error.
- A withdrawn or expired posting returns `NOT_FOUND` from `detail`. The API publishes no
  status field, so `isActive: true` means only "the portal still serves this posting".
- Endpoint and field documentation, including what to update if the portal changes, is in
  [`url-reference.md`](./url-reference.md).
