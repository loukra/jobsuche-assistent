---
name: instaffo-search
version: 1.0.0
description: >
  Use this skill to search for jobs on Instaffo (jobs.instaffo.com), a German
  tech- and business-focused job board covering Berlin, München, Hamburg,
  Frankfurt, Köln, Stuttgart, Düsseldorf and remote roles across Germany.
  Invoke for German job openings, vacancies and hiring in software engineering,
  data, product, consulting, sales, finance and HR. Trigger phrases: Instaffo,
  German jobs, jobs in Germany, Stellenangebote, Jobsuche, offene Stellen,
  Stellenanzeigen, Jobs in Berlin/München/Hamburg, Softwareentwickler Stellen,
  Arbeit suchen, bewerben, "gibt es X Jobs in <Stadt>".
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/instaffo-search/cli/src/cli.ts *)
---

# Instaffo Search Skill

Search live job listings from **Instaffo**'s public job board (`jobs.instaffo.com`),
a curated German job platform. No authentication, no API key, and **zero runtime
dependencies** — it runs with just `bun`.

## How this skill searches (read this first)

Instaffo has **no keyword-search endpoint that `robots.txt` permits**. Its free-text
search runs client-side against `/api/`, which `robots.txt` explicitly disallows, and
the `?search=` parameter on `/de/jobs` is inert server-side. This skill therefore
never calls a search endpoint. It reads the two server-rendered, robots-permitted
surfaces the portal advertises in its own sitemaps:

1. **Category pages** — `/de/jobs/<role>[-<city>]?page=N`, ~499 of them, 10 jobs per
   page with real server-side pagination. Used when the query (plus location) maps
   onto one, e.g. `-q "backend entwickler" -l "Berlin"` → `backend-entwickler-berlin`.
2. **The job sitemap** — `/sitemap-jobs.xml`, ~1,900 live German postings, used as a
   keyword index when no category matches, or whenever a location is requested that
   has no category page of its own.

Either way the index yields only id/title/url, so company, location and posting date
are **hydrated from each posting's detail page**. A search therefore costs a handful
of requests rather than one. The sitemaps are cached for an hour in your temp dir.

`meta.source` in the JSON output tells you which path answered (`category` or
`sitemap`), so you can always see how a result set was produced.

> **Courtesy note.** Every path used here is permitted by Instaffo's `robots.txt`;
> the disallowed `/api/`, `/apply` and `internal_utm_`-tagged URLs are deliberately
> not touched. Because search hydrates detail pages, still **keep volume low** —
> use `--limit`, and prefer a category-backed query where one exists.

## Commands

### Search job listings

```bash
bun run .agents/skills/instaffo-search/cli/src/cli.ts search [flags]
```

Flags — at least one of `--query` / `--location` is required:
- `--query <text>` / `-q <text>` — role or keywords, e.g. `"softwareentwickler"`, `"data engineer"`.
- `--location <text>` / `-l <text>` — German city or `remote`, e.g. `"Berlin"`, `"München"`, `"Flensburg"`. Umlauts are handled (`München` → `muenchen`).
- `--jobage <days>` — only postings published within N days. Filtered client-side on the posting's `datePosted` (see Notes — many Instaffo dates are old).
- `--page <n>` — 1-indexed. On the category path this is the portal's own page; on the sitemap path it advances the scan window.
- `--limit <n>` / `-n <n>` — cap results emitted (client-side).
- `--format json|table|plain` — default `json`.

### List the whole board

```bash
bun run .agents/skills/instaffo-search/cli/src/cli.ts index
```

Every live posting in the job sitemap (id, title from the slug, url) in **one** request,
without hydration. This is how to see everything: dedup the list against what you have
already seen and hydrate only the new postings with `detail`. The sitemap's `lastmod` is
the regeneration date of the whole file (all 3,554 entries carried today's date on
2026-10-26), so it says nothing about when a posting appeared, and `--jobage` on
`search` can only filter on the hydrated `datePosted`.

### Fetch full job detail

```bash
bun run .agents/skills/instaffo-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the value from `search` results (the posting slug, e.g.
`finanzbuchhalter-m-w-d-740946f4ab7d`). A bare 12-hex id (`740946f4ab7d`, resolved via
the sitemap) or a full `https://jobs.instaffo.com/de/job/...` URL also work. Returns the
full description, employment type, postal code, `validThrough`, and an active/expired flag.

## Usage examples

```bash
# Software engineering roles anywhere in Germany
bun run .agents/skills/instaffo-search/cli/src/cli.ts search -q "softwareentwickler" --limit 10 --format table

# Backend roles in Berlin (resolves to the backend-entwickler-berlin category page)
bun run .agents/skills/instaffo-search/cli/src/cli.ts search -q "backend entwickler" -l "Berlin" --format table

# Data roles in München, posted in the last 90 days
bun run .agents/skills/instaffo-search/cli/src/cli.ts search -q "data engineer" -l "München" --jobage 90 --format table

# Anything in a smaller city with no category page (uses the sitemap fallback)
bun run .agents/skills/instaffo-search/cli/src/cli.ts search -q "finanzbuchhalter" -l "Flensburg" --format table

# Remote product roles, second page
bun run .agents/skills/instaffo-search/cli/src/cli.ts search -q "product owner" -l "remote" --page 2 --format table

# Full details for one posting
bun run .agents/skills/instaffo-search/cli/src/cli.ts detail finanzbuchhalter-m-w-d-740946f4ab7d --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing ids to `detail`, reading `meta.source` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the
process exits with code `1`.

## Notes

Portal quirks found while building this skill (2026-08-31) — worth knowing before you
trust a result set:

- **Coverage is heavily skewed to the big hubs.** By category-page count: München
  (220), Berlin (185), remote (180), Hamburg (160), Frankfurt (160), Köln (150),
  Stuttgart (145), Düsseldorf (140). Smaller cities are very thin — **a city like Flensburg usually
  has none**. An empty result for a small city
  usually means Instaffo genuinely has nothing there, not that the search failed.
- **`datePosted` is often years old** while the posting is still listed and its
  `validThrough` is in the future. `--jobage 30` will therefore filter out most of the
  board. Use a generous window, or omit `--jobage` and read the dates yourself.
- **Instaffo's own description text has run-together words** — their JSON-LD flattens
  bullet lists without separators, producing things like
  `ZahlungsverkehrDurchführung der Debitoren-`. This is in the portal's source data,
  not a parsing bug, and it is left as-is rather than guessed at. Re-read the posting
  on the site before quoting it in a cover letter.
- **Slugs drift from titles.** A posting's URL slug reflects an older title
  (`java-softwareentwickler-full-stack-...` for a job now titled "Softwareentwickler –
  Schwerpunkt Angular"). The JSON-LD `title` is authoritative; `id` stays the slug
  because that is what addresses the page.
- **A city-scoped category page can still return out-of-city jobs** — e.g.
  `backend-entwickler-berlin` includes a München posting. That is Instaffo's own
  curation; pass `--location` on the sitemap path if you need a strict city filter.
- **Category anchor markup is unparseable by class name.** The CSS classes are
  build-hashed (`index-module-scss-module__oO5Yqa__root`) and change every deploy, so
  the CLI parses the page's JSON-LD `ItemList` instead. See `url-reference.md`.
- Postings are published in German and English at `/de/job/...` and `/en/job/...`;
  this skill reads the German set.
