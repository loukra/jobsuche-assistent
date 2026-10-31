// Data source: StepStone.de public job pages. No authentication required.
//
// Search  -> https://www.stepstone.de/jobs?q=…&where=…  returns a server-rendered
//            result list. Each posting is an <article data-at="job-item"
//            id="job-item-<id>">. The CSS class names are build-hashed
//            (res-xaz43y, res-kyg8or …) and change on every deploy, so every
//            parser below anchors on the stable `data-at` attributes instead.
// Detail  -> https://www.stepstone.de/stellenangebote--<slug>--<id>-inline.html
//            embeds a schema.org JobPosting as JSON-LD, which is far more stable
//            than the rendered markup. The <slug> is decorative: the server
//            resolves the posting from the numeric id alone, so we send a
//            placeholder.

export const BASE_URL = "https://www.stepstone.de"
export const SEARCH_URL = `${BASE_URL}/jobs`

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; stepstone-search-cli/1.0)"

/** Build a detail URL from a bare posting id. The slug segment is ignored by the server. */
export function detailUrl(id: string): string {
  return `${BASE_URL}/stellenangebote--x--${id}-inline.html`
}

/** Fetch HTML with exponential backoff on 429/5xx. Returns "" on a 404. */
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

export interface JobCard {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  workFromHome: string | null
  /** From the page's `unifiedSalary` payload, e.g. "39000–56000 € (StepStone-Schätzung)". */
  salary?: string | null
}

export interface JobDetail extends JobCard {
  description: string | null
  employmentType: string | null
  industry: string | null
  companyUrl: string | null
  validThrough: string | null
}

/**
 * Convert a Unicode code point to a string. Uses `fromCodePoint` (not
 * `fromCharCode`) so supplementary-plane code points decode correctly, and
 * drops out-of-range values instead of throwing.
 */
function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    // German pages lean on these heavily.
    .replace(/&auml;/g, "ä").replace(/&ouml;/g, "ö").replace(/&uuml;/g, "ü")
    .replace(/&Auml;/g, "Ä").replace(/&Ouml;/g, "Ö").replace(/&Uuml;/g, "Ü")
    .replace(/&szlig;/g, "ß")
    // Numeric character references: decimal (&#233;) and hexadecimal (&#xE9;).
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    // Ampersand last, so "&amp;lt;" does not become "<".
    .replace(/&amp;/g, "&")
}

/**
 * Drop <style>/<script> blocks wholesale. StepStone inlines an emotion <style>
 * element inside the first card that uses each generated class, and stripping
 * only the tags would leave the CSS rules behind as "text".
 */
export function stripStyleAndScript(html: string): string {
  return html.replace(/<(style|script)\b[^>]*>[\s\S]*?<\/\1>/gi, " ")
}

function stripTags(html: string): string {
  return stripStyleAndScript(html).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
}

function clean(html: string): string {
  return decodeHtmlEntities(stripTags(html))
}

/**
 * Read the text of the element carrying `data-at="<anchor>"`, tracking tag depth
 * so a nested <span> (StepStone wraps every field label in an icon span) does not
 * end the match at the first closing tag.
 */
export function textAt(html: string, anchor: string): string | null {
  const open = new RegExp(`<(\\w+)([^>]*\\sdata-at="${anchor}")[^>]*>`, "i").exec(html)
  if (!open) return null
  const tag = open[1].toLowerCase()
  const openRe = new RegExp(`<${tag}[\\s>]`, "gi")
  const closeRe = new RegExp(`</${tag}>`, "gi")

  let i = open.index + open[0].length
  let depth = 1
  while (depth > 0 && i < html.length) {
    openRe.lastIndex = i
    closeRe.lastIndex = i
    const nextOpen = openRe.exec(html)
    const nextClose = closeRe.exec(html)
    if (!nextClose) return null
    if (nextOpen && nextOpen.index < nextClose.index) {
      depth++
      i = nextOpen.index + nextOpen[0].length
    } else {
      depth--
      if (depth === 0) {
        return clean(html.slice(open.index + open[0].length, nextClose.index)) || null
      }
      i = nextClose.index + nextClose[0].length
    }
  }
  return null
}

/**
 * StepStone prints relative ages ("vor 6 Tagen", "Heute", "Gestern") rather than
 * timestamps. Convert to an ISO date so `date` is comparable across portals;
 * return the original string when it does not match a known shape, so an
 * unparsed value is still visible to the caller rather than silently dropped.
 */
export function parseRelativeDate(text: string | null, now: Date = new Date()): string | null {
  if (!text) return null
  const t = text.trim().toLowerCase()
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  const back = (days: number) => {
    const d = new Date(now)
    d.setUTCDate(d.getUTCDate() - days)
    return iso(d)
  }
  if (/heute|gerade|soeben/.test(t)) return iso(now)
  if (/gestern/.test(t)) return back(1)
  const m = t.match(/vor\s+(?:ca\.\s*)?(\d+)\s*(minute|minuten|stunde|stunden|tag|tagen|woche|wochen|monat|monaten)/)
  if (m) {
    const n = parseInt(m[1], 10)
    const unit = m[2]
    if (unit.startsWith("minute") || unit.startsWith("stunde")) return iso(now)
    if (unit.startsWith("tag")) return back(n)
    if (unit.startsWith("woche")) return back(n * 7)
    if (unit.startsWith("monat")) return back(n * 30)
  }
  // Already an absolute date (dd.mm.yyyy).
  const abs = t.match(/(\d{2})\.(\d{2})\.(\d{4})/)
  if (abs) return `${abs[3]}-${abs[2]}-${abs[1]}`
  return text.trim()
}

interface UnifiedSalary {
  salaryType?: string | null
  salaryAvailable?: boolean
  exactValue?: number | null
  min?: number | null
  max?: number | null
  period?: string | null
}

/**
 * The salary StepStone shows on each card lives in the page's inline JSON as
 * `unifiedSalary`, not in the card markup. Every card read on 2026-10-29 had
 * salaryType "Predicted": StepStone's own estimate, not the employer's band, so
 * that type is labelled as such. Keyed by posting id.
 */
export function parseSalaries(html: string): Map<string, string> {
  const text = html.replace(/&quot;|&#34;/g, '"')
  const out = new Map<string, string>()
  const re = /"unifiedSalary"\s*:\s*(\{[^{}]*\})/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const before = text.slice(Math.max(0, m.index - 4000), m.index)
    const ids = [...before.matchAll(/--(\d+)-inline\.html/g)]
    if (!ids.length) continue
    let s: UnifiedSalary
    try {
      s = JSON.parse(m[1])
    } catch {
      continue
    }
    const label = formatSalary(s)
    if (label) out.set(ids[ids.length - 1][1], label)
  }
  return out
}

export function formatSalary(s: UnifiedSalary): string | null {
  if (!s || s.salaryAvailable === false) return null
  const range =
    s.min != null && s.max != null ? `${s.min}–${s.max} €` : s.exactValue != null ? `${s.exactValue} €` : null
  if (!range) return null
  const period = /month/i.test(s.period || "") ? " monatlich" : ""
  const kind = /predict/i.test(s.salaryType || "") ? " (StepStone-Schätzung)" : ""
  return range + period + kind
}

/**
 * Parse the search result list. We split on the job-item <article> boundary and
 * parse each chunk independently, so one malformed card cannot break the rest.
 */
export function parseJobCards(html: string, now: Date = new Date()): JobCard[] {
  const results: JobCard[] = []
  const salaries = parseSalaries(html)
  const boundary = /<article[^>]*\sid="job-item-(\d+)"[^>]*\sdata-at="job-item"[^>]*>/gi

  const starts: { id: string; from: number }[] = []
  let m: RegExpExecArray | null
  while ((m = boundary.exec(html)) !== null) {
    starts.push({ id: m[1], from: m.index })
  }

  for (let i = 0; i < starts.length; i++) {
    const start = starts[i]
    const chunk = html.slice(start.from, i + 1 < starts.length ? starts[i + 1].from : html.length)

    const title = textAt(chunk, "job-item-title")
    if (!title) continue

    const hrefMatch = chunk.match(/<a[^>]*\shref="([^"]+)"[^>]*\sdata-at="job-item-title"/i)
      || chunk.match(/<a[^>]*\sdata-at="job-item-title"[^>]*\shref="([^"]+)"/i)
    let url = hrefMatch ? decodeHtmlEntities(hrefMatch[1]).split("?")[0] : ""
    if (url.startsWith("/")) url = BASE_URL + url

    results.push({
      id: start.id,
      title,
      company: textAt(chunk, "job-item-company-name"),
      location: textAt(chunk, "job-item-location"),
      date: parseRelativeDate(textAt(chunk, "job-item-timeago"), now),
      url: url || detailUrl(start.id),
      workFromHome: textAt(chunk, "job-item-work-from-home"),
      salary: salaries.get(start.id) ?? null,
    })
  }

  return results
}

/** Total matches the portal reports for the query, from its analytics payload. */
export function parseTotalCount(html: string): number | null {
  // The payload is HTML-escaped inline JSON; the escaping of the surrounding
  // quotes differs between responses (&quot; vs &#34;), so match loosely.
  const m = html.match(/searchResultsTotalJobCount(?:&quot;|&#34;|")?\s*:\s*(\d+)/)
  return m ? parseInt(m[1], 10) : null
}

interface JsonLdJobPosting {
  title?: string
  url?: string
  datePosted?: string
  validThrough?: string
  employmentType?: string
  industry?: string
  description?: string
  hiringOrganization?: { name?: string; url?: string }
  jobLocation?: { address?: { addressLocality?: string; addressRegion?: string; addressCountry?: string } }
}

/** Convert the description's HTML fragment to readable plain text. */
export function htmlToText(fragment: string): string {
  const withBreaks = stripStyleAndScript(fragment)
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "\n• ")
    .replace(/<\/(p|li|ul|ol|div|h\d|tr)>/gi, "\n")
  return decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, ""))
    .replace(/[ \t ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

/**
 * Parse the detail page's schema.org JobPosting JSON-LD. Falls back to null
 * fields rather than throwing when the block is missing or malformed, so a
 * markup change degrades instead of crashing.
 */
export function parseJobDetail(html: string, id: string): JobDetail | null {
  let data: JsonLdJobPosting | null = null
  const blockRe = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi
  let m: RegExpExecArray | null
  while ((m = blockRe.exec(html)) !== null) {
    try {
      const parsed = JSON.parse(m[1].trim())
      const candidates = Array.isArray(parsed) ? parsed : parsed["@graph"] ?? [parsed]
      for (const c of candidates) {
        if (c && c["@type"] === "JobPosting") {
          data = c as JsonLdJobPosting
          break
        }
      }
    } catch {
      // A single unparseable block must not hide a valid one later in the page.
      continue
    }
    if (data) break
  }
  if (!data) return null

  const addr = data.jobLocation?.address
  const location = [addr?.addressLocality, addr?.addressRegion]
    .filter((s) => s && s.trim())
    .join(", ") || null

  return {
    id,
    title: data.title ? decodeHtmlEntities(data.title) : "(untitled)",
    company: data.hiringOrganization?.name ?? null,
    companyUrl: data.hiringOrganization?.url ?? null,
    location,
    date: data.datePosted ? data.datePosted.slice(0, 10) : null,
    url: data.url ?? detailUrl(id),
    workFromHome: null,
    description: data.description ? htmlToText(data.description) || null : null,
    employmentType: data.employmentType ?? null,
    industry: data.industry ?? null,
    validThrough: data.validThrough ? data.validThrough.slice(0, 10) : null,
  }
}
