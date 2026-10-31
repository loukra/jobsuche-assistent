# arbeitsagentur-cli

CLI for the public JSON API behind **arbeitsagentur.de/jobsuche** (Bundesagentur für
Arbeit JOBBÖRSE, Germany). No authentication, no account, **zero runtime dependencies** —
plain `bun` + `fetch`. `bun install` pulls only dev types for `typecheck`.

## Install

```bash
cd .agents/skills/arbeitsagentur-search/cli && bun install
```

## Usage

```bash
bun run src/cli.ts search -q "Softwareentwickler" -l "Hamburg" --format table
bun run src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --limit 10
bun run src/cli.ts detail 13644-311617-S --format plain
bun run src/cli.ts --help
```

See [`../SKILL.md`](../SKILL.md) for the full flag reference and
[`../url-reference.md`](../url-reference.md) for the endpoints and response fields.

## Layout

| File | Purpose |
|------|---------|
| `src/cli.ts` | Flag parsing, validation, help text, command dispatch |
| `src/helpers.ts` | Endpoints, fetch with backoff, response mapping, parameter mapping |
| `src/commands/search.ts` | `search` — builds the query URL, renders json/table/plain |
| `src/commands/detail.ts` | `detail` — refnr normalisation, base64url addressing, rendering |

## Contract

Shared with every other portal skill in this repo, so `/scrape` can treat them alike:

- Commands `search` and `detail <id|url>`; flags `--query`/`-q`, `--location`/`-l`,
  `--jobage`, `--page`, `--limit`/`-n`, `--format json|table|plain`.
- Search JSON is `{ "meta": { "count", "page", "total" }, "results": [...] }`; every
  result has `id`, `title`, `company`, `location`, `date`, `url`, null (never omitted)
  when unknown.
- Errors go to **stderr** as `{ "error": "...", "code": "..." }`, exit code `1`.
  Unknown flags are rejected rather than silently dropped.
- Honest User-Agent (`Mozilla/5.0 (compatible; arbeitsagentur-search-cli/1.0)`),
  exponential backoff with jitter on 429/5xx, `null` on 404.

## Credentials

None required. Requests carry a fixed `X-API-Key: jobboerse-jobsuche` header taken from
the portal's public frontend config — a constant identifying the web client, not a
personal credential. Set `ARBEITSAGENTUR_API_KEY` to override it if the portal rotates
the value; a `403` response says so explicitly.

## Tests

```bash
bun run typecheck   # tsc --noEmit
bun run test        # bun test --timeout 30000
```

`tests/parsing.test.ts` runs offline against fixtures; `tests/search.test.ts` hits the
live portal (a handful of requests) and `tests/cli-flag-validation.test.ts` checks the
error contract.
