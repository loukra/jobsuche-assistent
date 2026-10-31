#!/usr/bin/env bun
// Self-contained CLI for searching jobs on StepStone.de's public job board.
// No external CLI framework and no runtime dependencies, so it runs anywhere
// `bun` is available with nothing installed beyond the repo clone.
//
// StepStone's robots.txt allows the search and posting paths this uses. It is
// still someone else's site: keep volume low and use it for your own job search.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit", p: "page" }
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

const HELP = `stepstone-cli — search jobs on StepStone.de (Germany)

USAGE
  bun run src/cli.ts search [--query "<text>"] [--location "<Ort>"] [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords: job title, skill, or company name.
  --location, -l <text>   German city or region, e.g. "Berlin", "München", "Nordrhein-Westfalen".
  --radius <km>           Search radius around the location in km (StepStone defaults to 30).
  --jobage <days>         Posted within N days. The portal honours only 1, 3, 7 and 14;
                          other values are rounded up (2 -> 3), above 14 means no filter.
                          meta.jobageApplied reports the bucket used. Default: all.
  --remote <mode>         remote (nur Home-Office) | hybrid (teilweise Home-Office).
  --page, -p <n>          1-indexed page (25 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --format table
  bun run src/cli.ts search -q "Projektmanager" -l "München" --radius 50 --format table
  bun run src/cli.ts search -q "Werkstudent Maschinenbau" -l "Hamburg" --format plain
  bun run src/cli.ts search -q "DevOps" --remote remote --jobage 14 --limit 10 --format table
  bun run src/cli.ts search -q "Controlling" -l "Nordrhein-Westfalen" -p 2
  bun run src/cli.ts detail 11713465 --format plain

At least one of --query or --location is required.
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/n/p to these before validation). "help"/"h" pass so
// `search --help` still prints usage.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "query", "location", "radius", "jobage", "remote", "page", "limit", "format", "help", "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  // Reject unknown flags instead of silently discarding them: a discarded
  // filter changes what the search returns with no error, and add-portal's
  // contract requires a bogus flag to exit 1 with a JSON error on stderr.
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
    // An empty search returns StepStone's undifferentiated full listing, which is
    // never what the caller meant; require at least one narrowing term.
    if (!query && !location) {
      process.stderr.write(
        JSON.stringify({
          error: 'at least one of --query/-q or --location/-l is required (e.g. -q "Data Engineer" -l "Berlin")',
          code: "NO_CRITERIA",
        }) + "\n",
      )
      return 1
    }

    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      const val = parseInt(raw as string, 10)
      if (isNaN(val)) {
        process.stderr.write(
          JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n",
        )
        return null
      }
      return val
    }

    let radius: number | undefined
    let jobage: number | undefined
    let page = 1
    let limit: number | undefined

    for (const [name, target] of [["radius", "radius"], ["jobage", "jobage"], ["page", "page"], ["limit", "limit"]] as const) {
      if (flags[name] === undefined) continue
      const v = parseIntFlag(name, flags[name])
      if (v === null) return 1
      if (target === "radius") radius = v
      if (target === "jobage") jobage = v
      if (target === "page") page = Math.max(1, v)
      if (target === "limit") limit = v
    }

    if (typeof flags.remote === "string" && !["remote", "hybrid"].includes(flags.remote.toLowerCase())) {
      process.stderr.write(
        JSON.stringify({
          error: `--remote must be "remote" or "hybrid", got "${flags.remote}"`,
          code: "BAD_ARG",
        }) + "\n",
      )
      return 1
    }

    const fmt = (flags.format as string) || "json"
    const opts: SearchOpts = {
      query,
      location,
      radius,
      jobage,
      remote: typeof flags.remote === "string" ? flags.remote : undefined,
      page,
      limit,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = { id, format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"] }
    return runDetail(opts)
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
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: "INTERNAL_ERROR",
      }) + "\n",
    )
    process.exit(1)
  })
