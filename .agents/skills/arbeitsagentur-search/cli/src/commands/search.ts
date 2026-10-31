import {
  SEARCH_URL,
  jsonFetch,
  jobageToVeroeffentlichtseit,
  offerTypeCode,
  workTimeCode,
  parseJobCards,
  parseTotal,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  radius?: number
  jobage: number
  offerType?: string
  worktime?: string
  field?: string
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/** The portal's page size. Requesting the cap keeps --limit a client-side trim. */
const PAGE_SIZE = 50

export function buildUrl(opts: SearchOpts): string {
  const params = new URLSearchParams()
  if (opts.query) params.set("was", opts.query)
  if (opts.location) params.set("wo", opts.location)
  if (opts.radius !== undefined) params.set("umkreis", String(opts.radius))
  const seit = jobageToVeroeffentlichtseit(opts.jobage)
  if (seit) params.set("veroeffentlichtseit", seit)
  const art = offerTypeCode(opts.offerType)
  if (art) params.set("angebotsart", art)
  const zeit = workTimeCode(opts.worktime)
  if (zeit) params.set("arbeitszeit", zeit)
  // berufsfeld: the portal's occupational-field facet, ';' joins several (OR).
  if (opts.field) params.set("berufsfeld", opts.field)
  params.set("page", String(opts.page))
  params.set("size", String(PAGE_SIZE))
  return `${SEARCH_URL}?${params.toString()}`
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "Keine Ergebnisse."
  const rows = cards.map((c) => {
    const id = c.id.slice(0, 28).padEnd(28)
    const title = (c.title || "").slice(0, 40).padEnd(40)
    const company = (c.company || "—").slice(0, 26).padEnd(26)
    const loc = (c.location || "—").slice(0, 22).padEnd(22)
    return `${id} ${title} ${company} ${loc} ${c.date || "—"}`
  })
  const header =
    "ID".padEnd(28) +
    " " +
    "TITEL".padEnd(40) +
    " " +
    "FIRMA".padEnd(26) +
    " " +
    "ORT".padEnd(22) +
    " DATUM"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const payload = await jsonFetch(buildUrl(opts))
    let cards = parseJobCards(payload)
    const total = parseTotal(payload)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          { meta: { count: cards.length, page: opts.page, total, jobageApplied: jobageToVeroeffentlichtseit(opts.jobage) }, results: cards },
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
