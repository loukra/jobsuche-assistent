import {
  SEARCH_URL,
  htmlFetch,
  parseJobCards,
  parseTotalCount,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  radius?: number
  jobage?: number
  remote?: string // "remote" | "hybrid"
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/** workFromHome facet: 1 = teilweise Home-Office (hybrid), 2 = nur Home-Office (remote). */
export function workFromHomeFlag(mode: string | undefined): string | null {
  switch ((mode || "").toLowerCase()) {
    case "remote":
      return "2"
    case "hybrid":
      return "1"
    default:
      return null
  }
}

/**
 * StepStone honours only ag=age_1, age_3, age_7 and age_14. Any other value is
 * silently dropped and the search returns every posting regardless of age
 * (measured 2026-10-26: age_2 and age_30 both gave the unfiltered total). So a
 * requested window is rounded UP to the next honoured bucket; beyond 14 days
 * there is no filter at all. Callers that need an exact window filter `date`.
 */
export const JOBAGE_BUCKETS = [1, 3, 7, 14]

export function jobageBucket(days: number | undefined): number | null {
  if (days === undefined || days <= 0 || days >= 9999) return null
  return JOBAGE_BUCKETS.find((b) => b >= days) ?? null
}

export function buildUrl(opts: SearchOpts): string {
  const params = new URLSearchParams()
  if (opts.query) params.set("q", opts.query)
  if (opts.location) params.set("where", opts.location)
  if (opts.radius !== undefined) params.set("radius", String(opts.radius))
  const age = jobageBucket(opts.jobage)
  if (age) params.set("ag", `age_${age}`)
  const wfh = workFromHomeFlag(opts.remote)
  if (wfh) params.set("wfh", wfh)
  if (opts.page > 1) params.set("page", String(opts.page))
  return `${SEARCH_URL}?${params.toString()}`
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header =
    "ID".padEnd(10) + " " + "TITLE".padEnd(44) + " " + "COMPANY".padEnd(26) + " " +
    "LOCATION".padEnd(22) + " DATE"
  const rows = cards.map((c) =>
    `${c.id.padEnd(10)} ${(c.title || "").slice(0, 44).padEnd(44)} ` +
    `${(c.company || "—").slice(0, 26).padEnd(26)} ` +
    `${(c.location || "—").slice(0, 22).padEnd(22)} ${c.date || "—"}`,
  )
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const html = await htmlFetch(buildUrl(opts))
    const total = parseTotalCount(html)
    let cards = parseJobCards(html)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        (cards.length === 0
          ? "No results."
          : cards
              .map(
                (c) =>
                  `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.date || "—"}` +
                  `${c.workFromHome ? ` · ${c.workFromHome}` : ""}\n  id: ${c.id}\n  ${c.url}`,
              )
              .join("\n\n")) + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          { meta: { count: cards.length, page: opts.page, total, jobageApplied: jobageBucket(opts.jobage) }, results: cards },
          null,
          2,
        ) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
