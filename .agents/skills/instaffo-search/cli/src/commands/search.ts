import {
  BASE,
  fetchCategorySlugs,
  fetchJobIndex,
  htmlFetch,
  hydrate,
  parseItemList,
  resolveCategory,
  slugify,
  tokens,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

/**
 * Upper bound on detail fetches per search. A location filter can only be
 * applied after hydration (most job slugs do not carry the city), so a narrow
 * city query would otherwise hydrate every keyword match on the board.
 */
const MAX_HYDRATE = 40

function withinAge(card: JobCard, days: number | undefined): boolean {
  if (days === undefined) return true
  if (!card.date) return true // undated postings are kept, not silently dropped
  const posted = new Date(card.date).getTime()
  if (isNaN(posted)) return true
  return (Date.now() - posted) / 86_400_000 <= days
}

function matchesLocation(card: JobCard, location: string | undefined): boolean {
  if (!location) return true
  const want = slugify(location)
  if (!want) return true
  const have = `${slugify(card.location || "")}-${slugify(card.id)}`
  return have.includes(want)
}

/** Category path: one server-rendered page of 10, with real server pagination. */
async function fromCategory(category: string, page: number): Promise<JobCard[]> {
  const url = `${BASE}/de/jobs/${category}${page > 1 ? `?page=${page}` : ""}`
  return parseItemList(await htmlFetch(url))
}

/**
 * Fallback path: keyword-filter the job sitemap, then page through the results
 * client-side. `page` advances the hydration window (MAX_HYDRATE candidates),
 * because the sitemap carries no company/location/date to filter on beforehand.
 */
async function fromSitemap(
  query: string | undefined,
  location: string | undefined,
  page: number,
): Promise<JobCard[]> {
  const index = await fetchJobIndex()
  const terms = query ? tokens(query) : []
  const matched = terms.length ? index.filter((e) => terms.every((t) => e.slug.includes(t))) : index

  // Freshest first — lastmod is the only ordering signal available pre-hydration.
  const byDate = (a: { lastmod: string | null }, b: { lastmod: string | null }) =>
    (b.lastmod || "").localeCompare(a.lastmod || "")

  // A location filter can only be applied after hydration, so postings whose
  // slug already names the city are hydrated first. Without this, a rare city
  // is never reached: the hydration window fills with the freshest postings
  // nationwide and the one matching job sits outside it.
  const loc = location ? slugify(location) : ""
  const ordered = loc
    ? [
        ...matched.filter((e) => e.slug.includes(loc)).sort(byDate),
        ...matched.filter((e) => !e.slug.includes(loc)).sort(byDate),
      ]
    : [...matched].sort(byDate)

  return ordered.slice((page - 1) * MAX_HYDRATE, page * MAX_HYDRATE).map((e) => ({
    id: e.slug,
    title: e.slug.replace(/-[0-9a-f]{12}$/, "").replace(/-/g, " "),
    company: null,
    location: null,
    date: null,
    url: e.url,
  }))
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header =
    "ID".padEnd(46) + " " + "TITLE".padEnd(40) + " " + "COMPANY".padEnd(24) + " " + "LOCATION".padEnd(16) + " DATE"
  const rows = cards.map(
    (c) =>
      `${c.id.slice(0, 46).padEnd(46)} ${(c.title || "").slice(0, 40).padEnd(40)} ` +
      `${(c.company || "—").slice(0, 24).padEnd(24)} ${(c.location || "—").slice(0, 16).padEnd(16)} ${c.date || "—"}`,
  )
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const categories = await fetchCategorySlugs()
    const resolved = resolveCategory(categories, opts.query, opts.location)
    const locSlug = opts.location ? slugify(opts.location) : ""

    // Only trust a category page when it is itself scoped to the requested
    // location. A bare role category is one 10-deep page of nationwide
    // postings; location-filtering that discards nearly everything and hides
    // matches that the sitemap would have found, so the fallback is better.
    const category = resolved && (!locSlug || resolved.includes(locSlug)) ? resolved : null

    let cards = category
      ? await fromCategory(category, opts.page)
      : await fromSitemap(opts.query, opts.location, opts.page)

    // A location-qualified category page is already scoped; every other path
    // needs the post-hydration filter.
    const needsLocationFilter = !!opts.location && !category

    cards = await hydrate(cards.slice(0, MAX_HYDRATE))
    if (needsLocationFilter) cards = cards.filter((c) => matchesLocation(c, opts.location))
    cards = cards.filter((c) => withinAge(c, opts.jobage))
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        (cards.length
          ? cards
              .map((c) => `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`)
              .join("\n\n")
          : "No results.") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          {
            meta: {
              count: cards.length,
              page: opts.page,
              source: category ? "category" : "sitemap",
              category: category ?? null,
            },
            results: cards,
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
