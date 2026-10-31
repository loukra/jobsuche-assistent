#!/usr/bin/env bun
// Self-contained CLI for the public JSON API behind arbeitsagentur.de/jobsuche
// (Bundesagentur für Arbeit JOBBÖRSE). No external CLI framework and zero
// runtime dependencies, so it runs anywhere `bun` is available.
//
// robots.txt on www.arbeitsagentur.de is "Allow: /", and these are the same
// endpoints the public search page calls. Still: keep volume low and use it
// for your own job search, not bulk collection.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit", r: "radius" }
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

const HELP = `arbeitsagentur-cli — search jobs on the Bundesagentur für Arbeit JOBBÖRSE (Germany)

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <refnr|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role) — the portal's "was".
  --location, -l <text>   City, postcode, or region — the portal's "wo". e.g. "Hamburg", "10247".
  --radius, -r <km>       Search radius around --location in km (portal's "umkreis").
  --jobage <days>         Published within N days. The portal honours only 1, 7, 14 and 28;
                          other values are rounded up (2 -> 7), above 28 means no filter.
  --offer-type <type>     arbeit | selbststaendigkeit | ausbildung | praktikum.
  --worktime <mode>       vollzeit | teilzeit | schicht | minijob. (homeoffice is rejected: the
                          API has returned 0 results for it since at least 2026-10-26; read
                          each result's "homeoffice" field instead.)
  --field <names>         Occupational field(s), the portal's "berufsfeld" facet, joined with
                          ";" for OR, e.g. "Informatik;Softwareentwicklung und Programmierung".
                          Counts as a search term on its own (no -q/-l needed).
                          meta.jobageApplied reports the age bucket actually used.
  --page <n>              1-indexed page (50 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "Softwareentwickler" -l "Hamburg" --format table
  bun run src/cli.ts search -q "Data Engineer" -l "Berlin" --jobage 7 --format table
  bun run src/cli.ts search -q "Pflegefachkraft" -l "München" -r 50 --worktime teilzeit --format table
  bun run src/cli.ts search -q "Mechatroniker" -l "Hamburg" --offer-type ausbildung --limit 10
  bun run src/cli.ts detail 13644-311617-S --format plain

Personal use only — keep volume low.
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/n/r to these before validation). "help"/"h" pass so
// `search --help` still prints usage.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "query", "location", "radius", "jobage", "offer-type", "worktime", "field", "page", "limit", "format", "help", "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

const OFFER_TYPES = ["arbeit", "selbststaendigkeit", "selbstaendigkeit", "freelance", "ausbildung", "praktikum", "trainee", "job"]
const WORKTIMES = ["vollzeit", "fulltime", "teilzeit", "parttime", "schicht", "minijob"]

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  // Reject unknown flags instead of silently discarding them: a discarded
  // filter changes what the search returns with no error.
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
    const field = typeof flags.field === "string" ? flags.field : undefined
    // The API happily returns the entire database for an empty query; that is
    // never what a user meant, so require at least one search term.
    if (!query && !location && !field) {
      process.stderr.write(
        JSON.stringify({
          error: 'pass at least --query/-q, --location/-l or --field (e.g. -q "Softwareentwickler" -l "Hamburg")',
          code: "NO_QUERY",
        }) + "\n",
      )
      return 1
    }

    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      const val = parseInt(raw as string, 10)
      if (isNaN(val)) {
        process.stderr.write(JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n")
        return null
      }
      return val
    }

    for (const name of ["jobage", "page", "limit", "radius"]) {
      if (flags[name] === undefined) continue
      const v = parseIntFlag(name, flags[name])
      if (v === null) return 1
      flags[name] = String(v)
    }

    if (flags["offer-type"] !== undefined) {
      const raw = String(flags["offer-type"]).toLowerCase()
      if (!OFFER_TYPES.includes(raw)) {
        process.stderr.write(
          JSON.stringify({ error: `--offer-type must be one of arbeit|selbststaendigkeit|ausbildung|praktikum, got "${flags["offer-type"]}"`, code: "BAD_ARG" }) + "\n",
        )
        return 1
      }
    }
    if (flags.worktime !== undefined) {
      const raw = String(flags.worktime).toLowerCase()
      if (!WORKTIMES.includes(raw)) {
        process.stderr.write(
          JSON.stringify({ error: `--worktime must be one of vollzeit|teilzeit|schicht|minijob, got "${flags.worktime}" (homeoffice returns 0 results on the current API; read each result's "homeoffice" field instead)`, code: "BAD_ARG" }) + "\n",
        )
        return 1
      }
    }

    const fmt = (flags.format as string) || "json"
    const opts: SearchOpts = {
      query,
      location,
      radius: flags.radius ? parseInt(flags.radius as string, 10) : undefined,
      jobage: flags.jobage ? parseInt(flags.jobage as string, 10) : 9999,
      offerType: typeof flags["offer-type"] === "string" ? flags["offer-type"] : undefined,
      worktime: typeof flags.worktime === "string" ? flags.worktime : undefined,
      field,
      page: flags.page ? Math.max(1, parseInt(flags.page as string, 10)) : 1,
      limit: flags.limit ? parseInt(flags.limit as string, 10) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires a <refnr|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = {
      id,
      format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"],
    }
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
