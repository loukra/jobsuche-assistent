// Data source: Workwise's own search service (`search.workwise.io`), the JSON API
// that backs the /jobsuche page. The public search page is client-rendered, so
// there is no server-rendered HTML to scrape - the API is the only usable path.
//
// Flow: POST /v2/searches creates a "search" (server-side tokenizes the free-text
// `description` into occupations), then GET /v2/searches/<id>/matchings pages the
// results. Detail comes from the public /job/<id> page, whose <head> carries a
// schema.org JobPosting JSON-LD block plus Next.js __NEXT_DATA__.

export const SEARCH_API = "https://search.workwise.io"
export const SITE = "https://www.workwise.io"

export const UA = "Mozilla/5.0 (compatible; workwise-cli/1.0)"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const MAX_RETRIES = 6

/** Sleep with jitter between backoff attempts. */
function backoff(delay: number): Promise<void> {
  const jitter = Math.floor(Math.random() * 500)
  return new Promise((r) => setTimeout(r, delay + jitter))
}

/**
 * Fetch with exponential backoff on 429/5xx. Returns `null` on a 404 rather
 * than throwing, so callers can report NOT_FOUND cleanly.
 */
async function request(url: string, init: RequestInit): Promise<Response | null> {
  let delay = 500
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const response = await fetch(url, {
      ...init,
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === MAX_RETRIES) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      await backoff(delay)
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return null
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response
  }
  throw new Error("Request failed after max retries")
}

export async function apiGet<T>(url: string): Promise<T | null> {
  const response = await request(url, {
    method: "GET",
    headers: { "User-Agent": UA, Accept: "application/json" },
  })
  return response ? ((await response.json()) as T) : null
}

export async function apiPost<T>(url: string, body: unknown): Promise<T | null> {
  const response = await request(url, {
    method: "POST",
    headers: {
      "User-Agent": UA,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  })
  return response ? ((await response.json()) as T) : null
}

/**
 * Fetch only the first `maxBytes` of a page, then cancel the stream.
 *
 * The detail page is ~250KB but the JSON-LD block (which carries `datePosted`)
 * ends well inside the first 16KB, and the server ignores Range requests. Reading
 * the head of the stream and aborting keeps date enrichment to ~1% of the
 * bandwidth a full page fetch would cost. Returns "" on a 404.
 */
export async function fetchHead(url: string, maxBytes = 32768): Promise<string> {
  const response = await request(url, {
    method: "GET",
    headers: {
      "User-Agent": UA,
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "de-DE,de;q=0.9",
    },
  })
  if (!response || !response.body) return ""

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let text = ""
  try {
    while (text.length < maxBytes) {
      const { done, value } = await reader.read()
      if (done) break
      text += decoder.decode(value, { stream: true })
    }
  } finally {
    // Cancel rather than drain: we deliberately abandon the rest of the body.
    await reader.cancel().catch(() => {})
  }
  return text
}

/** Fetch a full page as text. Returns "" on a 404. */
export async function fetchPage(url: string): Promise<string> {
  const response = await request(url, {
    method: "GET",
    headers: {
      "User-Agent": UA,
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "de-DE,de;q=0.9",
    },
  })
  return response ? await response.text() : ""
}

// ---------------------------------------------------------------------------
// Search filter payload
// ---------------------------------------------------------------------------

export interface LocationLevel {
  city: string
  country: string
  countryCode: string
  googlePlaceId: null
  id: number
  lat: number
  /** Radius in km. The API reuses `level` for the radius on search filters. */
  level: number
  lon: number
  prefix: string
  state: string
  stateCode: string
  zip: string
}

export interface SearchFilters {
  description: string
  end: null
  hoursEnd: null
  hoursStart: null
  languageLevels: never[]
  leadershipExperience: string
  locationLevels: LocationLevel[]
  mobileWork: null
  occupations: never[]
  ongoing: boolean
  remoteWork: string
  salary: null
  salaryFlexible: null
  salaryType: null
  searchCompanyLevels: never[]
  searchCompanyTagLevels: never[]
  searchesEnquiryTypes: never[]
  start: null
  workExperience: string
  worldwide: boolean
}

/**
 * The API rejects a partial body ("Search Api Validation Error"), so every key
 * the web client sends has to be present even when unset. These defaults are
 * lifted verbatim from the site's own default filter object.
 */
export function buildFilters(opts: {
  query?: string
  location?: LocationLevel
  remoteWork?: string
}): SearchFilters {
  return {
    description: opts.query ?? "",
    end: null,
    hoursEnd: null,
    hoursStart: null,
    languageLevels: [],
    leadershipExperience: "does_not_matter",
    locationLevels: opts.location ? [opts.location] : [],
    mobileWork: null,
    occupations: [],
    ongoing: true,
    remoteWork: opts.remoteWork ?? "does_not_matter",
    salary: null,
    salaryFlexible: null,
    salaryType: null,
    searchCompanyLevels: [],
    searchCompanyTagLevels: [],
    searchesEnquiryTypes: [],
    start: null,
    workExperience: "does_not_matter",
    worldwide: true,
  }
}

/** Map a user-facing --remote mode to the API's `remoteWork` filter value. */
export function remoteWorkFlag(mode: string | undefined): string | null {
  switch ((mode || "").toLowerCase()) {
    case "remote":
      return "entirely_wanted"
    case "onsite":
    case "on-site":
      return "not_wanted"
    case "":
      return "does_not_matter"
    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// Geocoding
// ---------------------------------------------------------------------------

/**
 * The location filter needs lat/lon - the site gets them from Google Places with
 * its own API key, which we cannot use. Rather than take on a third-party
 * geocoder dependency, we ship coordinates for the German cities a job search
 * realistically targets, and accept raw "lat,lon" for anywhere else.
 */
const CITIES: Record<string, [number, number, string, string]> = {
  berlin: [52.520008, 13.404954, "Berlin", "BE"],
  hamburg: [53.551086, 9.993682, "Hamburg", "HH"],
  münchen: [48.135125, 11.581981, "Bayern", "BY"],
  muenchen: [48.135125, 11.581981, "Bayern", "BY"],
  munich: [48.135125, 11.581981, "Bayern", "BY"],
  köln: [50.937531, 6.960279, "Nordrhein-Westfalen", "NRW"],
  koeln: [50.937531, 6.960279, "Nordrhein-Westfalen", "NRW"],
  cologne: [50.937531, 6.960279, "Nordrhein-Westfalen", "NRW"],
  "frankfurt am main": [50.110924, 8.682127, "Hessen", "HE"],
  frankfurt: [50.110924, 8.682127, "Hessen", "HE"],
  stuttgart: [48.775846, 9.182932, "Baden-Württemberg", "BW"],
  düsseldorf: [51.227741, 6.773456, "Nordrhein-Westfalen", "NRW"],
  duesseldorf: [51.227741, 6.773456, "Nordrhein-Westfalen", "NRW"],
  leipzig: [51.339695, 12.373075, "Sachsen", "SN"],
  dortmund: [51.513587, 7.465298, "Nordrhein-Westfalen", "NRW"],
  essen: [51.455643, 7.011555, "Nordrhein-Westfalen", "NRW"],
  bremen: [53.079296, 8.801694, "Bremen", "HB"],
  dresden: [51.050409, 13.737262, "Sachsen", "SN"],
  hannover: [52.375892, 9.73201, "Niedersachsen", "NI"],
  nürnberg: [49.452103, 11.076665, "Bayern", "BY"],
  nuernberg: [49.452103, 11.076665, "Bayern", "BY"],
  duisburg: [51.434408, 6.762329, "Nordrhein-Westfalen", "NRW"],
  bochum: [51.481845, 7.216236, "Nordrhein-Westfalen", "NRW"],
  wuppertal: [51.256213, 7.150764, "Nordrhein-Westfalen", "NRW"],
  bielefeld: [52.030228, 8.532471, "Nordrhein-Westfalen", "NRW"],
  bonn: [50.73743, 7.098207, "Nordrhein-Westfalen", "NRW"],
  münster: [51.960665, 7.626135, "Nordrhein-Westfalen", "NRW"],
  muenster: [51.960665, 7.626135, "Nordrhein-Westfalen", "NRW"],
  karlsruhe: [49.006889, 8.403653, "Baden-Württemberg", "BW"],
  mannheim: [49.487459, 8.466039, "Baden-Württemberg", "BW"],
  augsburg: [48.370545, 10.89779, "Bayern", "BY"],
  wiesbaden: [50.078218, 8.239761, "Hessen", "HE"],
  mönchengladbach: [51.180099, 6.442519, "Nordrhein-Westfalen", "NRW"],
  moenchengladbach: [51.180099, 6.442519, "Nordrhein-Westfalen", "NRW"],
  gelsenkirchen: [51.517744, 7.085717, "Nordrhein-Westfalen", "NRW"],
  braunschweig: [52.268874, 10.526771, "Niedersachsen", "NI"],
  chemnitz: [50.827845, 12.921369, "Sachsen", "SN"],
  kiel: [54.323293, 10.122765, "Schleswig-Holstein", "SH"],
  aachen: [50.775346, 6.083887, "Nordrhein-Westfalen", "NRW"],
  halle: [51.482778, 11.97389, "Sachsen-Anhalt", "ST"],
  magdeburg: [52.120533, 11.627624, "Sachsen-Anhalt", "ST"],
  freiburg: [47.999008, 7.842104, "Baden-Württemberg", "BW"],
  krefeld: [51.339327, 6.585154, "Nordrhein-Westfalen", "NRW"],
  lübeck: [53.865467, 10.686559, "Schleswig-Holstein", "SH"],
  luebeck: [53.865467, 10.686559, "Schleswig-Holstein", "SH"],
  oberhausen: [51.496527, 6.851527, "Nordrhein-Westfalen", "NRW"],
  erfurt: [50.984768, 11.02988, "Thüringen", "TH"],
  mainz: [49.992862, 8.247253, "Rheinland-Pfalz", "RP"],
  rostock: [54.09244, 12.099147, "Mecklenburg-Vorpommern", "MV"],
  kassel: [51.312801, 9.481544, "Hessen", "HE"],
  hagen: [51.367455, 7.463218, "Nordrhein-Westfalen", "NRW"],
  saarbrücken: [49.240368, 6.996379, "Saarland", "SL"],
  saarbruecken: [49.240368, 6.996379, "Saarland", "SL"],
  potsdam: [52.390569, 13.064473, "Brandenburg", "BB"],
  regensburg: [49.013432, 12.101624, "Bayern", "BY"],
  ingolstadt: [48.76508, 11.423786, "Bayern", "BY"],
  würzburg: [49.791304, 9.953355, "Bayern", "BY"],
  wuerzburg: [49.791304, 9.953355, "Bayern", "BY"],
  heidelberg: [49.398752, 8.672434, "Baden-Württemberg", "BW"],
  ulm: [48.401082, 9.987608, "Baden-Württemberg", "BW"],
  darmstadt: [49.878708, 8.646927, "Hessen", "HE"],
  osnabrück: [52.279911, 8.047179, "Niedersachsen", "NI"],
  osnabrueck: [52.279911, 8.047179, "Niedersachsen", "NI"],
  jena: [50.927054, 11.589237, "Thüringen", "TH"],
  tübingen: [48.520999, 9.057645, "Baden-Württemberg", "BW"],
  tuebingen: [48.520999, 9.057645, "Baden-Württemberg", "BW"],
  göttingen: [51.541811, 9.915795, "Niedersachsen", "NI"],
  goettingen: [51.541811, 9.915795, "Niedersachsen", "NI"],
  // Bremen / north-west Lower Saxony. "Oldenburg" here is Oldenburg (Oldb) in
  // Niedersachsen — the ~170k city next to Bremen — not the much smaller
  // Oldenburg in Holstein (Schleswig-Holstein, 54.29/10.89). Pass that one's
  // coordinates explicitly if you ever want it.
  oldenburg: [53.143722, 8.213622, "Niedersachsen", "NI"],
  bremerhaven: [53.539584, 8.580942, "Bremen", "HB"],
  delmenhorst: [53.05066, 8.630833, "Niedersachsen", "NI"],
  wilhelmshaven: [53.529507, 8.113806, "Niedersachsen", "NI"],
  // Ammerland / Friesland
  westerstede: [53.256944, 7.926944, "Niedersachsen", "NI"],
  "bad zwischenahn": [53.183333, 8.009722, "Niedersachsen", "NI"],
  varel: [53.396944, 8.136111, "Niedersachsen", "NI"],
  jever: [53.574444, 7.900556, "Niedersachsen", "NI"],
  // Ostfriesland
  leer: [53.231667, 7.452778, "Niedersachsen", "NI"],
  aurich: [53.470833, 7.483611, "Niedersachsen", "NI"],
  emden: [53.367222, 7.206111, "Niedersachsen", "NI"],
  norden: [53.594722, 7.205, "Niedersachsen", "NI"],
  wittmund: [53.575833, 7.780278, "Niedersachsen", "NI"],
  // Emsland / Grafschaft Bentheim
  papenburg: [53.078056, 7.402222, "Niedersachsen", "NI"],
  meppen: [52.690556, 7.291667, "Niedersachsen", "NI"],
  lingen: [52.523333, 7.318611, "Niedersachsen", "NI"],
  nordhorn: [52.432222, 7.066944, "Niedersachsen", "NI"],
  // Oldenburger Münsterland / Mittelweser
  cloppenburg: [52.847500, 8.045000, "Niedersachsen", "NI"],
  vechta: [52.726389, 8.286111, "Niedersachsen", "NI"],
  diepholz: [52.606944, 8.370556, "Niedersachsen", "NI"],
  verden: [52.922500, 9.230556, "Niedersachsen", "NI"],
  nienburg: [52.638611, 9.211667, "Niedersachsen", "NI"],
  // Elbe-Weser
  rotenburg: [53.111389, 9.408333, "Niedersachsen", "NI"],
  cuxhaven: [53.858889, 8.693056, "Niedersachsen", "NI"],
  stade: [53.593056, 9.475556, "Niedersachsen", "NI"],
}

export interface GeocodeResult {
  location: LocationLevel
  matchedCity: string
}

/**
 * Resolve a --location string to a LocationLevel filter entry. Accepts a known
 * German city name (case- and umlaut-tolerant) or an explicit "lat,lon" pair.
 */
export function geocode(input: string, radiusKm: number): GeocodeResult | null {
  const trimmed = input.trim()

  const coords = trimmed.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/)
  if (coords) {
    return {
      matchedCity: trimmed,
      location: {
        // `city` must be non-empty. The API derives a `limiter` from which
        // fields are set: an empty city yields limiter "country_code", which
        // silently ignores lat/lon and the radius and returns nationwide
        // results. A non-empty city yields limiter "city", which applies the
        // radius. The string itself is never matched — coordinates do the
        // filtering — so the raw pair doubles as a self-documenting label.
        city: trimmed,
        country: "Deutschland",
        countryCode: "DE",
        googlePlaceId: null,
        id: -1,
        lat: parseFloat(coords[1]!),
        level: radiusKm,
        lon: parseFloat(coords[2]!),
        prefix: "",
        state: "",
        stateCode: "",
        zip: "",
      },
    }
  }

  const entry = CITIES[trimmed.toLowerCase()]
  if (!entry) return null
  const [lat, lon, state, stateCode] = entry
  return {
    matchedCity: trimmed,
    location: {
      city: trimmed,
      country: "Deutschland",
      countryCode: "DE",
      googlePlaceId: null,
      id: -1,
      lat,
      level: radiusKm,
      lon,
      prefix: "",
      state,
      stateCode,
      zip: "",
    },
  }
}

export function knownCities(): string[] {
  return Object.keys(CITIES).sort()
}

// ---------------------------------------------------------------------------
// Response shapes and mapping
// ---------------------------------------------------------------------------

interface ApiLocationLevel {
  city?: string | null
  state?: string | null
  country?: string | null
  zip?: string | null
}

interface ApiEnquiry {
  id: number
  name: string
  slug?: string | null
  status?: string | null
  shortDescription?: string | null
  minSalary?: string | null
  maxSalary?: string | null
  hoursStart?: number | null
  hoursEnd?: number | null
  remoteWork?: string | null
  isEnquiryNew?: boolean
  locationLevels?: ApiLocationLevel[]
  company?: { name?: string | null; slug?: string | null } | null
  type?: { name?: string | null } | null
}

export interface ApiMatching {
  enquiries: ApiEnquiry
  score?: number
}

export interface MatchingsResponse {
  data: { matchings: ApiMatching[] }
  paging: { page: number; pages: number; size: number; total: number }
}

export interface SearchCreateResponse {
  data: { search: { id: number } }
}

export interface JobResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  employmentType: string | null
  remoteWork: string | null
  hoursPerWeek: string | null
  salary: string | null
  isNew: boolean
  shortDescription: string | null
  score: number | null
}

/** Render a job's location list as a single human-readable string. */
function formatLocations(levels: ApiLocationLevel[] | undefined): string | null {
  if (!levels || levels.length === 0) return null
  const names = levels
    .map((l) => l.city || l.state || l.country)
    .filter((n): n is string => Boolean(n))
  if (names.length === 0) return null
  const unique = [...new Set(names)]
  return unique.length > 3 ? `${unique.slice(0, 3).join(", ")} +${unique.length - 3}` : unique.join(", ")
}

function formatSalary(min?: string | null, max?: string | null): string | null {
  const lo = min ? Math.round(parseFloat(min)) : null
  const hi = max ? Math.round(parseFloat(max)) : null
  if (lo === null && hi === null) return null
  if (lo !== null && hi !== null) return lo === hi ? `${lo} €` : `${lo}–${hi} €`
  return `${lo ?? hi} €`
}

function formatHours(start?: number | null, end?: number | null): string | null {
  if (start == null && end == null) return null
  if (start != null && end != null) return start === end ? `${start} h` : `${start}–${end} h`
  return `${start ?? end} h`
}

export function jobUrl(id: number | string, slug?: string | null): string {
  return slug ? `${SITE}/job/${id}-${slug}` : `${SITE}/job/${id}`
}

export function mapMatching(m: ApiMatching): JobResult {
  const e = m.enquiries
  return {
    id: String(e.id),
    title: e.name,
    company: e.company?.name ?? null,
    location: formatLocations(e.locationLevels),
    // The search API carries no posting date; `search --with-dates` and
    // `--jobage` fill this in from each posting's page. See url-reference.md.
    date: null,
    url: jobUrl(e.id, e.slug),
    employmentType: e.type?.name ?? null,
    remoteWork: e.remoteWork ?? null,
    hoursPerWeek: formatHours(e.hoursStart, e.hoursEnd),
    salary: formatSalary(e.minSalary, e.maxSalary),
    isNew: Boolean(e.isEnquiryNew),
    shortDescription: e.shortDescription ?? null,
    score: typeof m.score === "number" ? m.score : null,
  }
}

// ---------------------------------------------------------------------------
// Detail-page parsing
// ---------------------------------------------------------------------------

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
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    // &amp; last, so "&amp;lt;" does not become "<".
    .replace(/&amp;/g, "&")
}

/**
 * Turn a description's HTML into readable plain text, keeping paragraph and
 * list-item breaks as newlines and prefixing list items with a bullet.
 */
export function htmlToText(html: string): string {
  return decodeHtmlEntities(
    html
      .replace(/<\s*br\s*\/?>/gi, "\n")
      .replace(/<\s*li[^>]*>/gi, "\n• ")
      .replace(/<\/(p|li|ul|ol|div|h\d|tr)>/gi, "\n")
      .replace(/<[^>]+>/g, ""),
  )
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

export interface JsonLdJobPosting {
  title?: string
  datePosted?: string
  validThrough?: string
  employmentType?: string | string[]
  description?: string
  workHours?: string
  skills?: string
  occupationalCategory?: string
  directApply?: boolean
  hiringOrganization?: { name?: string; sameAs?: string }
  jobLocation?: Array<{
    address?: {
      addressLocality?: string
      addressRegion?: string
      addressCountry?: string
      postalCode?: string
    }
  }>
  baseSalary?: {
    currency?: string
    value?: { minValue?: string; maxValue?: string; unitText?: string }
  }
}

/**
 * Pull the schema.org JobPosting block out of a detail page's <head>. Parsed
 * independently of __NEXT_DATA__ so a change to either one still leaves the
 * other usable.
 */
export function parseJsonLd(html: string): JsonLdJobPosting | null {
  const re = /<script type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    try {
      const parsed = JSON.parse(m[1]!)
      if (parsed && parsed["@type"] === "JobPosting") return parsed as JsonLdJobPosting
    } catch {
      // A non-JobPosting block that fails to parse must not abort the scan.
      continue
    }
  }
  return null
}

export interface NextEnquiry {
  id: number
  name: string
  slug?: string | null
  status?: string | null
  description?: string | null
  shortDescription?: string | null
  firstPublished?: string | null
  lastPublished?: string | null
  hoursStart?: number | null
  hoursEnd?: number | null
  minSalary?: string | null
  maxSalary?: string | null
  remoteWork?: string | null
  language?: string | null
  type?: { name?: string | null } | null
  company?: { name?: string | null; slug?: string | null } | null
  locationLevels?: ApiLocationLevel[]
  toolLevels?: Array<{ tool?: { name?: string | null } | null; level?: string | null }>
  languageLevels?: Array<{ language?: { name?: string | null } | null; level?: string | null }>
}

/** Pull `pageProps.enquiry` out of the detail page's __NEXT_DATA__ blob. */
export function parseNextEnquiry(html: string): NextEnquiry | null {
  const m = html.match(
    /<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/,
  )
  if (!m) return null
  try {
    const data = JSON.parse(m[1]!)
    return (data?.props?.pageProps?.enquiry as NextEnquiry) ?? null
  } catch {
    return null
  }
}

/** Read just `datePosted` from a page head, for cheap date enrichment. */
export function parseDatePosted(html: string): string | null {
  const ld = parseJsonLd(html)
  if (ld?.datePosted) return ld.datePosted
  const m = html.match(/"datePosted"\s*:\s*"([^"]+)"/)
  return m ? m[1]! : null
}

export interface JobDetail extends JobResult {
  description: string | null
  validThrough: string | null
  skills: string | null
  occupationalCategory: string | null
  companyUrl: string | null
  directApply: boolean | null
  status: string | null
  language: string | null
}

export function parseJobDetail(html: string, id: string): JobDetail | null {
  const ld = parseJsonLd(html)
  const enquiry = parseNextEnquiry(html)
  if (!ld && !enquiry) return null

  const employmentType = enquiry?.type?.name
    ?? (Array.isArray(ld?.employmentType) ? ld!.employmentType.join(", ") : ld?.employmentType)
    ?? null

  const address = ld?.jobLocation?.[0]?.address
  const location =
    formatLocations(enquiry?.locationLevels) ??
    (address?.addressLocality || address?.addressRegion || null)

  const salaryValue = ld?.baseSalary?.value
  const salary =
    formatSalary(enquiry?.minSalary, enquiry?.maxSalary) ??
    formatSalary(salaryValue?.minValue, salaryValue?.maxValue)

  const description = enquiry?.description
    ? htmlToText(enquiry.description)
    : ld?.description
      ? htmlToText(ld.description)
      : null

  return {
    id,
    title: enquiry?.name ?? ld?.title ?? "(untitled)",
    company: enquiry?.company?.name ?? ld?.hiringOrganization?.name ?? null,
    location,
    date: enquiry?.firstPublished ?? ld?.datePosted ?? null,
    url: jobUrl(id, enquiry?.slug),
    employmentType,
    remoteWork: enquiry?.remoteWork ?? null,
    hoursPerWeek: formatHours(enquiry?.hoursStart, enquiry?.hoursEnd) ?? ld?.workHours ?? null,
    salary,
    isNew: false,
    shortDescription: enquiry?.shortDescription ?? null,
    score: null,
    description,
    validThrough: ld?.validThrough ?? null,
    skills: ld?.skills ?? null,
    occupationalCategory: ld?.occupationalCategory?.trim() || null,
    companyUrl: ld?.hiringOrganization?.sameAs ?? null,
    directApply: typeof ld?.directApply === "boolean" ? ld.directApply : null,
    status: enquiry?.status ?? null,
    language: enquiry?.language ?? null,
  }
}
