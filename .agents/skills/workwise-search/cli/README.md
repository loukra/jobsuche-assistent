# workwise-cli

CLI for searching jobs on **Workwise** (`workwise.io`), a German job board. Zero runtime
dependencies — plain `bun` + `fetch`. `bun install` pulls dev types only.

## Install

```bash
cd .agents/skills/workwise-search/cli && bun install && cd ../../../..
```

The install is optional: the CLI runs on a fresh clone with nothing but `bun`. It only
adds `typescript` and `@types/bun` so `bun run typecheck` works.

## Usage

```bash
bun run src/cli.ts search [flags]
bun run src/cli.ts detail <id|url> [--format json|plain]
bun run src/cli.ts --help
```

### Search flags

| Flag | Meaning |
|------|---------|
| `--query`, `-q <text>` | Keywords (job title, skill, role) |
| `--location`, `-l <text>` | German city (`"Berlin"`) or `"lat,lon"` — matches that location **plus remote jobs** |
| `--radius <km>` | Radius around `--location`. Default `30` |
| `--remote <mode>` | `remote` or `onsite` (the portal has no hybrid filter) |
| `--jobage <days>` | Keep only postings published within N days |
| `--with-dates` | Fill in publication dates without filtering |
| `--page <n>` | 1-indexed page (25 results/page) |
| `--limit`, `-n <n>` | Cap results emitted (client-side) |
| `--format <fmt>` | `json` (default), `table`, `plain` |

### Examples

```bash
bun run src/cli.ts search -q "Data Engineer" --format table
bun run src/cli.ts search -q "Softwareentwickler" -l "Berlin" --radius 30 --format table
bun run src/cli.ts search -q "DevOps" --remote remote --jobage 30 --limit 10 --format table
bun run src/cli.ts detail 123632 --format plain
```

## Output

`search --format json` follows the repo's portal-skill contract:

```json
{
  "meta": { "count": 2, "page": 1, "pages": 1, "total": 7, "searchId": 219827592 },
  "results": [
    {
      "id": "123632",
      "title": "Data Engineer für Microsoft Fabric (m/w/d)",
      "company": "rheindata GmbH",
      "location": "Köln",
      "date": null,
      "url": "https://www.workwise.io/job/123632-data-engineer-fuer-microsoft-fabric-m-w-d",
      "employmentType": "Festanstellung",
      "remoteWork": "not_possible",
      "hoursPerWeek": "40 h",
      "salary": null,
      "isNew": false,
      "shortDescription": "…",
      "score": 40.57
    }
  ]
}
```

Missing values are `null`, never omitted. Errors go to **stderr** as
`{ "error": "...", "code": "..." }` with exit code `1`.

## Why `date` is null

The search API carries no publication date and offers no posting-age filter — see
`../url-reference.md`. `--with-dates` and `--jobage` fill it in by reading each posting's
page, at **one extra request per result**, so pair them with `--limit`. The CLI reads only
the head of each page and cancels the rest of the download, keeping a date lookup near
10 KB instead of the full 250 KB page.

## How it works

Two-step API flow against Workwise's own search service:

1. `POST search.workwise.io/v2/searches` with the site's full default filter object
   (a partial body is rejected) → returns a `searchId`.
2. `GET search.workwise.io/v2/searches/<id>/matchings?size&page` → returns results and `paging`.

`detail` fetches the server-rendered `workwise.io/job/<id>` page and merges its
schema.org JSON-LD block with `__NEXT_DATA__.props.pageProps.enquiry`, so a change to
either payload leaves the other usable.

The `/jobsuche` page itself is client-rendered and contains no results, so HTML scraping
is not an option for search. Parsing anchors and traps are documented in
`../url-reference.md` — read it before repairing anything here.

## Development

```bash
bun run typecheck   # tsc --noEmit
bun run test        # bun test --timeout 30000
```

The suite mixes offline parsing tests with live smoke tests against the portal. Live
tests make a handful of real requests — keep it that way.
