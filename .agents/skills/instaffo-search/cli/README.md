# instaffo-cli

Search jobs on [Instaffo](https://jobs.instaffo.com)'s public German job board.
No authentication, no API key, **zero runtime dependencies** — plain `bun` + `fetch`.

```bash
bun install   # dev types only (typescript, @types/bun)

bun run src/cli.ts search -q "softwareentwickler" -l "Berlin" --format table
bun run src/cli.ts detail finanzbuchhalter-m-w-d-740946f4ab7d --format plain
bun run src/cli.ts --help
```

## Why there is no search endpoint

Instaffo's free-text search runs client-side against `/api/`, which `robots.txt`
disallows, and `?search=` is inert server-side. So `search` is built from the two
robots-permitted, server-rendered surfaces the portal advertises in its sitemaps:
its ~499 **category pages** (`/de/jobs/<role>[-<city>]?page=N`) and its **job
sitemap** (~1,900 postings) as a keyword index. Both give id/title/url only, so
company/location/date are hydrated from each posting's detail page — a search costs
several requests, so keep `--limit` modest. Sitemaps are cached for an hour in the
system temp dir.

`meta.source` in the JSON output reports which path answered: `category` or `sitemap`.

Full endpoint and parsing notes: [`../url-reference.md`](../url-reference.md).

## Output shape

```json
{
  "meta": { "count": 2, "page": 1, "source": "sitemap", "category": null },
  "results": [
    {
      "id": "finanzbuchhalter-m-w-d-740946f4ab7d",
      "title": "Finanzbuchhalter (m/w/d)",
      "company": "Treuhand Weser-Ems GmbH Wirtschaftsprüfungsgesellschaft",
      "location": "Flensburg",
      "date": "2025-02-28",
      "url": "https://jobs.instaffo.com/de/job/finanzbuchhalter-m-w-d-740946f4ab7d"
    }
  ]
}
```

Missing values are `null`, never omitted. Errors go to **stderr** as
`{ "error": "...", "code": "..." }` with exit code `1`.

## Scripts

| Script | What it does |
|---|---|
| `bun run start` | Runs the CLI |
| `bun run test` | Unit tests + live smoke tests against the portal |
| `bun run typecheck` | `tsc --noEmit` |

`bun test` hits the live site — keep runs occasional.
