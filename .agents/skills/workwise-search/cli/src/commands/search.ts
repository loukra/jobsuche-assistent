import {
  SEARCH_API,
  apiGet,
  apiPost,
  buildFilters,
  fetchHead,
  geocode,
  knownCities,
  mapMatching,
  parseDatePosted,
  writeError,
  type JobResult,
  type MatchingsResponse,
  type SearchCreateResponse,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  radius: number
  remote?: string
  remoteWork: string
  jobage?: number
  withDates: boolean
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/** Workwise's own page size. Kept in step with the site so `--page` lines up. */
const PAGE_SIZE = 25

/**
 * Fill in `date` for each result from its posting page.
 *
 * The search API returns no posting date, so this is the only way to get one.
 * It costs one request per result, so it runs only under `--with-dates` or
 * `--jobage`. Requests go out in small batches to keep concurrent load on the
 * portal low; a posting whose date cannot be read keeps `date: null` rather
 * than failing the whole search.
 */
async function enrichDates(results: JobResult[], batchSize = 4): Promise<void> {
  for (let i = 0; i < results.length; i += batchSize) {
    const batch = results.slice(i, i + batchSize)
    await Promise.all(
      batch.map(async (job) => {
        try {
          const head = await fetchHead(job.url)
          job.date = head ? parseDatePosted(head) : null
        } catch {
          job.date = null
        }
      }),
    )
  }
}

function renderTable(jobs: JobResult[]): string {
  if (jobs.length === 0) return "No results."
  const rows = jobs.map((j) => {
    const title = (j.title || "").slice(0, 44).padEnd(44)
    const company = (j.company || "—").slice(0, 24).padEnd(24)
    const loc = (j.location || "—").slice(0, 22).padEnd(22)
    const date = (j.date ? j.date.slice(0, 10) : "—").padEnd(10)
    return `${j.id.padEnd(8)} ${title} ${company} ${loc} ${date}`
  })
  const header =
    "ID".padEnd(8) +
    " " +
    "TITLE".padEnd(44) +
    " " +
    "COMPANY".padEnd(24) +
    " " +
    "LOCATION".padEnd(22) +
    " " +
    "DATE".padEnd(10)
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

function renderPlain(jobs: JobResult[]): string {
  if (jobs.length === 0) return "No results."
  return jobs
    .map((j) =>
      [
        j.title,
        `  ${j.company || "—"} · ${j.location || "—"} · ${j.date ? j.date.slice(0, 10) : "—"}`,
        `  ${[j.employmentType, j.hoursPerWeek, j.salary].filter(Boolean).join(" · ") || "—"}`,
        `  id: ${j.id}`,
        `  ${j.url}`,
      ].join("\n"),
    )
    .join("\n\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    let location
    if (opts.location) {
      const geo = geocode(opts.location, opts.radius)
      if (!geo) {
        writeError(
          `unknown location "${opts.location}" - pass a known German city or an explicit "lat,lon" pair. Known cities: ${knownCities().join(", ")}`,
          "UNKNOWN_LOCATION",
        )
        return 1
      }
      location = geo.location
    }

    // Step 1: create a search. The API tokenizes the free-text query server-side
    // into occupations, so the search id is what the result pages hang off.
    const filters = buildFilters({
      query: opts.query,
      location,
      remoteWork: opts.remoteWork,
    })
    const created = await apiPost<SearchCreateResponse>(`${SEARCH_API}/v2/searches`, filters)
    const searchId = created?.data?.search?.id
    if (!searchId) {
      writeError("search service did not return a search id", "SEARCH_FAILED")
      return 1
    }

    // Step 2: page the matchings for that search.
    const url = `${SEARCH_API}/v2/searches/${searchId}/matchings?size=${PAGE_SIZE}&page=${opts.page}`
    const matchings = await apiGet<MatchingsResponse>(url)
    if (!matchings) {
      writeError("search results not found", "NOT_FOUND")
      return 1
    }

    let results = (matchings.data?.matchings ?? []).map(mapMatching)
    if (opts.limit !== undefined && opts.limit >= 0) results = results.slice(0, opts.limit)

    if (opts.withDates || opts.jobage !== undefined) {
      await enrichDates(results)
    }
    if (opts.jobage !== undefined) {
      const cutoff = Date.now() - opts.jobage * 86400000
      // A posting with no readable date is dropped rather than kept: --jobage
      // asks for postings known to be recent, and an unknown date is not that.
      results = results.filter((j) => j.date !== null && Date.parse(j.date) >= cutoff)
    }

    if (opts.format === "table") {
      process.stdout.write(renderTable(results) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(renderPlain(results) + "\n")
    } else {
      const paging = matchings.paging ?? { page: opts.page, pages: 1, size: PAGE_SIZE, total: 0 }
      process.stdout.write(
        JSON.stringify(
          {
            meta: {
              count: results.length,
              page: paging.page ?? opts.page,
              pages: paging.pages ?? null,
              total: paging.total ?? null,
              searchId,
            },
            results,
          },
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
