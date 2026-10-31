// Data source: Instaffo's public job board (jobs.instaffo.com). No authentication,
// no API key, zero runtime dependencies.
//
// IMPORTANT — why this skill does not call a search endpoint:
// Instaffo's free-text search runs client-side against /api/, which robots.txt
// explicitly disallows. The `?search=` query parameter on /de/jobs is inert
// server-side (it returns the unfiltered page). So `search` is built from the two
// robots-permitted, server-rendered surfaces instead:
//   1. Category pages  /de/jobs/<role>[-<city>]?page=N  — advertised in
//      sitemap-category-pages.xml, 10 jobs/page, real server-side pagination.
//   2. The job sitemap /sitemap-jobs.xml — advertised for crawling, ~1.9k live
//      German postings, used as a keyword index when no category matches.
// Both yield id/title/url only, so company/location/date are hydrated from each
// posting's detail page.

import { tmpdir } from "node:os"
import { join } from "node:path"

export const BASE = "https://jobs.instaffo.com"
export const SITEMAP_JOBS = `${BASE}/sitemap-jobs.xml`
export const SITEMAP_CATEGORIES = `${BASE}/sitemap-category-pages.xml`

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; instaffo-search-cli/1.0)"

/** Fetch with exponential backoff + jitter on 429/5xx. Returns "" on a 404. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return ""
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

// ---------------------------------------------------------------------------
// Slug handling
// ---------------------------------------------------------------------------

/**
 * Normalise free text to Instaffo's slug alphabet. German umlauts are
 * transliterated the way the portal spells its own category slugs
 * (München -> muenchen, Düsseldorf -> duesseldorf, Köln -> koeln), which is
 * NOT what a plain accent-strip produces (that would give "munchen").
 */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

/** Tokens used for keyword matching against a job slug. */
export function tokens(text: string): string[] {
  return slugify(text).split("-").filter((t) => t.length > 1)
}

/** The trailing 12-hex segment that uniquely identifies an Instaffo posting. */
export function hexId(slugOrUrl: string): string | null {
  const m = slugOrUrl.match(/([0-9a-f]{12})(?:[/?#]|$)/i)
  return m ? m[1].toLowerCase() : null
}

// ---------------------------------------------------------------------------
// Disk cache (the job sitemap is ~2.5 MB; refetching it per search is rude)
// ---------------------------------------------------------------------------

const CACHE_TTL_MS = 60 * 60 * 1000 // 1 hour

function cachePath(key: string): string {
  return join(tmpdir(), `instaffo-search-${key}.json`)
}

async function cached<T>(key: string, produce: () => Promise<T>): Promise<T> {
  const path = cachePath(key)
  try {
    const file = Bun.file(path)
    if (await file.exists()) {
      const { at, data } = (await file.json()) as { at: number; data: T }
      if (Date.now() - at < CACHE_TTL_MS) return data
    }
  } catch {
    // Unreadable or corrupt cache is not an error — just refetch.
  }
  const data = await produce()
  try {
    await Bun.write(path, JSON.stringify({ at: Date.now(), data }))
  } catch {
    // A read-only tmpdir must not break the search.
  }
  return data
}

// ---------------------------------------------------------------------------
// Sitemaps
// ---------------------------------------------------------------------------

export interface IndexEntry {
  slug: string
  url: string
  lastmod: string | null
}

/** Every German job URL in sitemap-jobs.xml, with its lastmod. */
export async function fetchJobIndex(): Promise<IndexEntry[]> {
  return cached("jobs", async () => {
    const xml = await htmlFetch(SITEMAP_JOBS)
    const entries: IndexEntry[] = []
    // Parse per <url> block so a malformed entry cannot shift the lastmod of
    // the following one.
    for (const block of xml.split("<url>").slice(1)) {
      const loc = block.match(/<loc>(https:\/\/jobs\.instaffo\.com\/de\/job\/[^<]+)<\/loc>/)
      if (!loc) continue
      const lastmod = block.match(/<lastmod>([^<]+)<\/lastmod>/)
      entries.push({
        slug: loc[1].replace(`${BASE}/de/job/`, ""),
        url: loc[1],
        lastmod: lastmod ? lastmod[1] : null,
      })
    }
    return entries
  })
}

/** Every German category slug in sitemap-category-pages.xml. */
export async function fetchCategorySlugs(): Promise<string[]> {
  return cached("categories", async () => {
    const xml = await htmlFetch(SITEMAP_CATEGORIES)
    const slugs = new Set<string>()
    const re = /<loc>https:\/\/jobs\.instaffo\.com\/de\/jobs\/([^<]+)<\/loc>/g
    let m: RegExpExecArray | null
    while ((m = re.exec(xml)) !== null) slugs.add(m[1])
    return [...slugs]
  })
}

/**
 * Pick the category page that best covers a query (+ optional location).
 * Prefers the location-qualified slug, then the bare role slug. Returns null
 * when neither exists, which sends the caller to the sitemap fallback.
 */
export function resolveCategory(
  slugs: string[],
  query: string | undefined,
  location: string | undefined,
): string | null {
  const available = new Set(slugs)
  const q = query ? slugify(query) : ""
  const loc = location ? slugify(location) : ""
  const candidates: string[] = []
  if (q && loc) candidates.push(`${q}-${loc}`)
  if (q) candidates.push(q)
  if (!q && loc) candidates.push(loc, `${loc}-jobs`)
  for (const c of candidates) if (available.has(c)) return c
  return null
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

/** Pull every JSON-LD object out of a page, flattening @graph and arrays. */
function jsonLdObjects(html: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  const re = /<script[^>]+application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    let parsed: unknown
    try {
      parsed = JSON.parse(m[1])
    } catch {
      continue // one bad block must not lose the others
    }
    const stack = [parsed]
    while (stack.length) {
      const node = stack.pop()
      if (Array.isArray(node)) stack.push(...node)
      else if (node && typeof node === "object") {
        const obj = node as Record<string, unknown>
        out.push(obj)
        if (Array.isArray(obj["@graph"])) stack.push(...(obj["@graph"] as unknown[]))
      }
    }
  }
  return out
}

export interface JobCard {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
}

export interface JobDetail extends JobCard {
  description: string | null
  employmentType: string | null
  postalCode: string | null
  country: string | null
  validThrough: string | null
  isActive: boolean
}

/**
 * Parse a category page's job list from its JSON-LD ItemList.
 *
 * Deliberately not parsed from the DOM: the anchor class names are build-hashed
 * (index-module-scss-module__oO5Yqa__root) and change on every deploy, and the
 * anchor hrefs carry internal_utm_* params that robots.txt disallows. The
 * ItemList carries clean canonical URLs and the real (unslugged) job titles.
 */
export function parseItemList(html: string): JobCard[] {
  const results: JobCard[] = []
  const seen = new Set<string>()
  for (const obj of jsonLdObjects(html)) {
    if (obj["@type"] !== "ItemList" || !Array.isArray(obj.itemListElement)) continue
    for (const raw of obj.itemListElement as unknown[]) {
      const item = raw as Record<string, unknown>
      const url = typeof item.url === "string" ? item.url : null
      const name = typeof item.name === "string" ? item.name : null
      if (!url || !url.includes("/de/job/")) continue
      const slug = url.split("/de/job/")[1]?.split(/[?#]/)[0]
      if (!slug || seen.has(slug)) continue
      seen.add(slug)
      results.push({
        id: slug,
        title: name || slug,
        company: null,
        location: null,
        date: null,
        url: `${BASE}/de/job/${slug}`,
      })
    }
  }
  return results
}

/**
 * Strip invisible characters the portal embeds in names and copy: soft hyphens
 * (U+00AD, e.g. "Wirt\u00adschafts\u00adpruefungs\u00adgesellschaft") and
 * zero-width spaces/joiners. They render as nothing but corrupt string
 * comparisons and make CV/cover-letter copy-paste subtly wrong.
 */
function stripInvisibles(text: string): string {
  return text.replace(/[\u00ad\u200b-\u200d\ufeff]/g, "")
}

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&#(\d+);/g, (_, d) => {
      const cp = parseInt(d, 10)
      return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
    })
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, h) => {
      const cp = parseInt(h, 16)
      return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
    })
}

/** HTML description -> readable text, keeping paragraph breaks. */
function htmlToText(html: string): string {
  return stripInvisibles(decodeEntities(
    html
      .replace(/<\s*br\s*\/?>/gi, "\n")
      .replace(/<\/(p|li|ul|ol|div|h\d|tr)>/gi, "\n")
      .replace(/<li[^>]*>/gi, "- ")
      .replace(/<[^>]+>/g, ""),
  ))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

/** Parse a posting's schema.org JobPosting JSON-LD. */
export function parseJobPosting(html: string, slug: string): JobDetail | null {
  const posting = jsonLdObjects(html).find((o) => o["@type"] === "JobPosting")
  if (!posting) return null

  const org = posting.hiringOrganization as Record<string, unknown> | undefined
  const rawLoc = posting.jobLocation
  const locObj = (Array.isArray(rawLoc) ? rawLoc[0] : rawLoc) as Record<string, unknown> | undefined
  const address = locObj?.address as Record<string, unknown> | undefined

  const str = (v: unknown): string | null => {
    if (typeof v !== "string") return null
    const cleaned = stripInvisibles(decodeEntities(v)).trim()
    return cleaned || null
  }

  const employmentType = Array.isArray(posting.employmentType)
    ? (posting.employmentType as unknown[]).filter((t) => typeof t === "string").join(", ") || null
    : str(posting.employmentType)

  const validThrough = str(posting.validThrough)
  // validThrough in the past means the posting has expired. Absence of the
  // field is absence of evidence, not proof it is open.
  const isActive = validThrough ? new Date(validThrough).getTime() >= Date.now() : true

  return {
    id: slug,
    title: str(posting.title) || slug,
    company: str(org?.name),
    location: str(address?.addressLocality),
    date: str(posting.datePosted),
    url: `${BASE}/de/job/${slug}`,
    description: posting.description ? htmlToText(String(posting.description)) || null : null,
    employmentType,
    postalCode: str(address?.postalCode),
    country: str(address?.addressCountry),
    validThrough,
    isActive,
  }
}

/** Fetch a posting's detail page and parse it. Returns null when not found. */
export async function fetchDetail(slug: string): Promise<JobDetail | null> {
  const html = await htmlFetch(`${BASE}/de/job/${slug}`)
  if (!html) return null
  return parseJobPosting(html, slug)
}

/**
 * Hydrate cards with company/location/date from their detail pages, at low
 * concurrency to keep request volume gentle. A card whose detail fetch fails
 * keeps its id/title/url rather than disappearing from the results.
 */
export async function hydrate(cards: JobCard[], concurrency = 3): Promise<JobCard[]> {
  const out: JobCard[] = new Array(cards.length)
  let next = 0
  const workers = Array.from({ length: Math.min(concurrency, cards.length) }, async () => {
    while (true) {
      const i = next++
      if (i >= cards.length) return
      const card = cards[i]
      try {
        const detail = await fetchDetail(card.id)
        out[i] = detail
          ? { ...card, title: detail.title || card.title, company: detail.company, location: detail.location, date: detail.date }
          : card
      } catch {
        out[i] = card
      }
    }
  })
  await Promise.all(workers)
  return out
}
