# stepstone-cli

Command-line search for **StepStone.de**, Germany's largest commercial job board.

Zero runtime dependencies — plain `bun` + `fetch` + regex parsing. `bun install`
pulls only TypeScript and `@types/bun` for `typecheck`.

## Install

```bash
cd .agents/skills/stepstone-search/cli && bun install
```

Optional: the CLI runs without installing anything if you don't need `typecheck`.

## Usage

```bash
bun run src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --format table
bun run src/cli.ts search -q "DevOps" --remote remote --limit 10
bun run src/cli.ts detail 14438124 --format plain
bun run src/cli.ts --help
```

At least one of `--query`/`-q` or `--location`/`-l` is required for `search`.
See `../SKILL.md` for the full flag reference and `../url-reference.md` for the
endpoint and parsing documentation.

## Output contract

`search --format json` (the default) emits:

```json
{ "meta": { "count": 2, "page": 1, "total": 119 }, "results": [ … ] }
```

Each result carries `id`, `title`, `company`, `location`, `date`, `url`, and
`workFromHome`. Missing values are `null`, never omitted.

Errors go to **stderr** as `{"error": "...", "code": "..."}` with exit code `1`.
Unknown flags are rejected rather than silently ignored — a discarded filter would
change what the search returns with no visible error.

## Development

```bash
bun run typecheck   # tsc --noEmit
bun run test        # bun test --timeout 30000
```

`tests/parsing.test.ts` is offline and runs against fixtures in StepStone's real
shape. `tests/live-smoke.test.ts` hits the live site — keep it small.

StepStone's CSS class names are build-hashed and change on every deploy, so every
parser anchors on `data-at="…"` attributes. If parsing breaks, start at
`../url-reference.md`, which records each anchor and the two traps (inline `<style>`
blocks inside cards, nested icon `<span>`s inside the company/location fields).
