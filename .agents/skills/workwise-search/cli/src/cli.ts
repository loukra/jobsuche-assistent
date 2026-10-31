#!/usr/bin/env bun
// Self-contained CLI for searching jobs on Workwise (workwise.io), Germany.
// No external CLI framework and zero runtime dependencies, so it runs anywhere
// `bun` is available with nothing installed beyond the repo clone.
//
// Data comes from Workwise's own search service (search.workwise.io), the JSON
// API that backs the site's /jobsuche page — the page itself is client-rendered,
// so there is no server-rendered HTML to parse. See url-reference.md.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { remoteWorkFlag, writeError } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
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

const HELP = `workwise-cli — search jobs on Workwise (workwise.io, Germany)

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role), e.g. "Data Engineer".
  --location, -l <text>   German city (e.g. "Berlin", "München") or "lat,lon".
  --radius <km>           Radius around --location. Default 30.
  --remote <mode>         remote | onsite. Filter by remote-work preference.
  --jobage <days>         Keep only postings published within N days. Costs one
                          extra request per result (see --with-dates).
  --with-dates            Fill in each result's publication date. The search API
                          returns no date, so this reads each posting's page.
  --page <n>              1-indexed page (25 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "Data Engineer" --format table
  bun run src/cli.ts search -q "Softwareentwickler" -l "Berlin" --radius 30 --format table
  bun run src/cli.ts search -q "Werkstudent Informatik" -l "München" --limit 10 --format table
  bun run src/cli.ts search -q "DevOps" --remote remote --jobage 30 --format table
  bun run src/cli.ts search -q "Controlling" -l "Hamburg" --page 2 --format json
  bun run src/cli.ts detail 110689 --format plain
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/n to these before validation). "help"/"h" pass so `search --help`
// still prints usage.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "query", "location", "radius", "remote", "jobage", "with-dates",
    "page", "limit", "format", "help", "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

function parseIntFlag(name: string, raw: string | boolean | string[]): number | null {
  const val = parseInt(raw as string, 10)
  if (isNaN(val)) {
    writeError(`--${name} must be a number, got "${raw}"`, "BAD_ARG")
    return null
  }
  return val
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
      writeError(
        `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
        "UNKNOWN_FLAG",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const fmt = (flags.format as string) || "json"

    const remote = typeof flags.remote === "string" ? flags.remote : undefined
    const remoteWork = remoteWorkFlag(remote)
    if (remoteWork === null) {
      writeError(`--remote must be "remote" or "onsite", got "${flags.remote}"`, "BAD_ARG")
      return 1
    }

    let radius = 30
    if (flags.radius !== undefined) {
      const v = parseIntFlag("radius", flags.radius)
      if (v === null) return 1
      if (v <= 0) {
        writeError(`--radius must be a positive number, got "${flags.radius}"`, "BAD_ARG")
        return 1
      }
      radius = v
    }

    let jobage: number | undefined
    if (flags.jobage !== undefined) {
      const v = parseIntFlag("jobage", flags.jobage)
      if (v === null) return 1
      if (v <= 0) {
        writeError(`--jobage must be a positive number of days, got "${flags.jobage}"`, "BAD_ARG")
        return 1
      }
      jobage = v
    }

    let page = 1
    if (flags.page !== undefined) {
      const v = parseIntFlag("page", flags.page)
      if (v === null) return 1
      page = Math.max(1, v)
    }

    let limit: number | undefined
    if (flags.limit !== undefined) {
      const v = parseIntFlag("limit", flags.limit)
      if (v === null) return 1
      limit = v
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      location: typeof flags.location === "string" ? flags.location : undefined,
      radius,
      remote,
      remoteWork,
      jobage,
      withDates: flags["with-dates"] === true,
      page,
      limit,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      writeError("detail requires an <id|url>", "NO_ID")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = {
      id,
      format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"],
    }
    return runDetail(opts)
  }

  writeError(`Unknown command "${cmd}"`, "BAD_CMD")
  return 1
}

main()
  // exitCode, not process.exit(): exiting while stdout is a pipe drops any
  // output beyond the first 64 KB (seen with freehire -n 100).
  .then((code) => {
    process.exitCode = code
  })
  .catch((e) => {
    writeError(e instanceof Error ? e.message : String(e), "INTERNAL_ERROR")
    process.exit(1)
  })
