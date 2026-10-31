#!/usr/bin/env bun
// Self-contained CLI for searching jobs on Instaffo's public job board
// (jobs.instaffo.com, German market). No authentication, no API key, and zero
// runtime dependencies — it runs with just `bun`.
//
// Instaffo exposes no robots-permitted free-text search endpoint (its search is
// client-side against the disallowed /api/ path), so `search` reads the
// server-rendered category pages and the public job sitemap instead. See
// helpers.ts and url-reference.md for the full rationale.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { fetchJobIndex } from "./helpers.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("--") || a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `instaffo-cli — search jobs on Instaffo (jobs.instaffo.com, Germany)

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]
  bun run src/cli.ts index [--format json]

INDEX
  Lists every live posting in the public job sitemap (id, title from the slug,
  url) in one request, without hydration: no company, location or date. This is
  the complete board, so a caller can dedup against what it has already seen
  and hydrate only the new postings with \`detail\`. The sitemap's lastmod is
  the regeneration date of the whole file, not a posting date.

SEARCH FLAGS
  --query, -q <text>      Role or keywords, e.g. "backend entwickler", "data engineer".
  --location, -l <text>   German city or "remote", e.g. "Berlin", "München", "Flensburg".
  --jobage <days>         Only postings published within N days (filtered client-side).
  --page <n>              1-indexed page (10 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

DETAIL
  <id|url>                The id from search results (a slug), a bare 12-hex id,
                          or a full https://jobs.instaffo.com/de/job/... URL.

EXAMPLES
  bun run src/cli.ts search -q "softwareentwickler" -l "Flensburg" --format table
  bun run src/cli.ts search -q "backend entwickler" -l "Berlin" --format table
  bun run src/cli.ts search -q "data engineer" --jobage 30 --limit 5 --format table
  bun run src/cli.ts search -q "product owner" -l "remote" --page 2 --format table
  bun run src/cli.ts detail java-entwickler-backend-m-w-430f12a0768e --format plain

NOTE
  Instaffo has no public keyword-search endpoint that robots.txt permits, so
  --query is matched against the portal's own category pages first and against
  the public job sitemap otherwise. Results are hydrated from each posting's
  detail page, so a search costs a few requests. Keep volume low.
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "location", "jobage", "page", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
  index: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  // Reject unknown flags rather than silently discarding them: a dropped filter
  // changes what the search returns with no error.
  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({
          error: `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
          code: "UNKNOWN_FLAG",
        }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const query = typeof flags.query === "string" ? flags.query : undefined
    const location = typeof flags.location === "string" ? flags.location : undefined
    if (!query && !location) {
      process.stderr.write(
        JSON.stringify({
          error: 'search needs at least --query/-q or --location/-l (e.g. -q "softwareentwickler" -l "Flensburg")',
          code: "NO_CRITERIA",
        }) + "\n",
      )
      return 1
    }

    const numeric: Record<string, number> = {}
    for (const name of ["jobage", "page", "limit"]) {
      if (flags[name] === undefined) continue
      const raw = flags[name]
      const val = parseInt(raw as string, 10)
      if (isNaN(val)) {
        process.stderr.write(
          JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n",
        )
        return 1
      }
      if (val < 0) {
        process.stderr.write(
          JSON.stringify({ error: `--${name} must not be negative, got "${raw}"`, code: "BAD_ARG" }) + "\n",
        )
        return 1
      }
      numeric[name] = val
    }

    const fmt = (flags.format as string) || "json"
    const opts: SearchOpts = {
      query,
      location,
      jobage: numeric.jobage,
      page: numeric.page !== undefined ? Math.max(1, numeric.page) : 1,
      limit: numeric.limit,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "index") {
    const entries = await fetchJobIndex()
    const results = entries.map((e) => ({
      id: e.slug,
      title: e.slug.replace(/-[0-9a-f]{12}$/, "").replace(/-/g, " "),
      url: e.url,
    }))
    process.stdout.write(JSON.stringify({ meta: { count: results.length }, results }, null, 2) + "\n")
    return 0
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    return runDetail({ id, format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"] })
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  // exitCode, not process.exit(): exiting while stdout is a pipe drops any
  // output beyond the first 64 KB (seen with freehire -n 100).
  .then((code) => {
    process.exitCode = code
  })
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({ error: e instanceof Error ? e.message : String(e), code: "INTERNAL_ERROR" }) + "\n",
    )
    process.exit(1)
  })
