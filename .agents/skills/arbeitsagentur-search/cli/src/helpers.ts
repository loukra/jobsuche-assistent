// Data source: the public JSON API behind arbeitsagentur.de/jobsuche (the
// Bundesagentur für Arbeit JOBBÖRSE). The endpoints and the API key below are
// read straight out of the portal's own frontend config
// (https://www.arbeitsagentur.de/jobsuche/config/config.js) — they are the
// same calls the public search page makes in a browser. No user account, no
// OAuth, no billing: the key is a fixed public constant identifying the
// frontend, not a personal credential, so it is not read from the environment
// (ARBEITSAGENTUR_API_KEY overrides it only for when the portal rotates it).
//
// Responses are JSON, so there is no HTML parsing here. Each result is mapped
// independently in `parseJobCards`, so one malformed record cannot break the rest.

export const SEARCH_URL =
  "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
export const DETAIL_URL =
  "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails"

const API_KEY = process.env.ARBEITSAGENTUR_API_KEY || "jobboerse-jobsuche"

const UA = "Mozilla/5.0 (compatible; arbeitsagentur-search-cli/1.0)"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

/** Fetch JSON with exponential backoff on 429/5xx. Returns null on a 404. */
export async function jsonFetch(url: string): Promise<unknown | null> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        "X-API-Key": API_KEY,
        Accept: "application/json",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(15000),
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
    if (response.status === 404) return null
    if (response.status === 403) {
      throw new Error(
        "Request failed: 403 Forbidden — the portal rejected the API key. " +
          "It is baked into the public frontend and is rotated occasionally; " +
          "re-read it from https://www.arbeitsagentur.de/jobsuche/config/config.js " +
          "and set ARBEITSAGENTUR_API_KEY, or update helpers.ts.",
      )
    }
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.json()
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
  region: string | null
  profession: string | null
  offerType: string | null
  homeoffice: boolean | null
  fulltime: boolean | null
  contractDuration: string | null
  entryDate: string | null
  distanceKm: number | null
  externalUrl: string | null
}

export interface JobDetail extends JobCard {
  description: string | null
  salary: string | null
  temporaryAgency: boolean | null
  privatePlacement: boolean | null
  careerChangerFriendly: boolean | null
  isActive: boolean
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v.trim() : null
}

/**
 * The API spells "unknown" as a KEINE_ANGABE(N) enum rather than omitting the
 * field. Surfacing that verbatim reads as data; per the output contract an
 * unknown value is null.
 */
function enumStr(v: unknown): string | null {
  const raw = str(v)
  if (!raw || /^KEINE_ANGABEN?$/i.test(raw)) return null
  return raw
}

/** SCREAMING_SNAKE enum (UNBEFRISTET) -> "Unbefristet". */
function formatEnum(v: unknown): string | null {
  const raw = enumStr(v)
  if (!raw) return null
  return raw
    .toLowerCase()
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ")
}

function bool(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null
}

function obj(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null
}

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

/**
 * Descriptions arrive as plain text with real newlines, but a minority of
 * employer-supplied bodies still carry stray tags or entities. Normalise both
 * without collapsing the paragraph breaks that make the text readable.
 */
export function cleanDescription(raw: unknown): string | null {
  const text = str(raw)
  if (!text) return null
  const withBreaks = text
    .replace(/<\s*br\s*\/?>/gi, "\n")
    // A paragraph close is a blank line; list items and headings are one break.
    .replace(/<\/(p|div)>/gi, "\n\n")
    .replace(/<\/(li|ul|ol|h\d)>/gi, "\n")
  return (
    decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
      // Bodies are stored as Markdown, so punctuation arrives backslash-escaped
      // ("C\#", "R&D \& more"). Unescape exactly the CommonMark set, leaving
      // any other backslash (Windows paths, regexes in a job ad) alone.
      .replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g, "$1")
      .replace(/[ \t]+/g, " ")
      .replace(/ *\n */g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim() || null
  )
}

/** SCREAMING_SNAKE region codes (NORDRHEIN_WESTFALEN) → "Nordrhein Westfalen". */
export function formatRegion(raw: unknown): string | null {
  const code = str(raw)
  if (!code) return null
  return code
    .toLowerCase()
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ")
}

/** "20095 Hamburg" from the first of possibly several locations. */
function formatLocation(locations: unknown): { location: string | null; region: string | null } {
  if (!Array.isArray(locations) || locations.length === 0) {
    return { location: null, region: null }
  }
  const address = obj(obj(locations[0])?.adresse)
  if (!address) return { location: null, region: null }
  const parts = [str(address.plz), str(address.ort)].filter(Boolean)
  let location = parts.join(" ") || null
  if (location && locations.length > 1) location += ` (+${locations.length - 1})`
  return { location, region: formatRegion(address.region) }
}

/** Employment-agency offer-type enums are already human-readable; title them. */
function formatOfferType(raw: unknown): string | null {
  const code = str(raw)
  if (!code) return null
  return code.charAt(0) + code.slice(1).toLowerCase()
}

function formatSalary(record: Record<string, unknown>): string | null {
  const from = num(record.gehaltsspanneVon)
  const to = num(record.gehaltsspanneBis)
  const kind = formatEnum(record.artDerVerguetung) ?? formatEnum(record.verguetungsangabe)
  if (from === null && to === null) return kind
  const range =
    from !== null && to !== null
      ? `${from}–${to} EUR`
      : `${from ?? to} EUR`
  return kind ? `${range} (${kind})` : range
}

/** Public posting page for a reference number. */
export function jobUrl(refnr: string): string {
  return `https://www.arbeitsagentur.de/jobsuche/jobdetail/${encodeURIComponent(refnr)}`
}

/** The detail endpoint addresses a posting by the base64url of its refnr. */
export function encodeRefnr(refnr: string): string {
  return Buffer.from(refnr, "utf8").toString("base64url")
}

function mapCard(record: Record<string, unknown>): JobCard | null {
  const id = str(record.referenznummer)
  if (!id) return null
  const title = str(record.stellenangebotsTitel) ?? str(record.hauptberuf)
  if (!title) return null

  const { location, region } = formatLocation(record.stellenlokationen)
  const published = obj(record.veroeffentlichungszeitraum)
  const entry = obj(record.eintrittszeitraum)
  const date =
    str(published?.von) ??
    str(record.datumErsteVeroeffentlichung) ??
    str(record.aenderungsdatum)?.slice(0, 10) ??
    null

  return {
    id,
    title,
    company: str(record.firma),
    location,
    date,
    url: jobUrl(id),
    region,
    profession: str(record.hauptberuf),
    offerType: formatOfferType(record.stellenangebotsart),
    homeoffice: bool(record.homeofficemoeglich),
    fulltime: bool(record.arbeitszeitVollzeit),
    contractDuration: formatEnum(record.vertragsdauer),
    entryDate: str(entry?.von),
    distanceKm: num(record.entfernung),
    externalUrl: str(record.externeURL),
  }
}

/**
 * Map the search response's `ergebnisliste`. Each record is mapped inside its
 * own try/catch so one malformed posting cannot break the whole page.
 */
export function parseJobCards(payload: unknown): JobCard[] {
  const list = obj(payload)?.ergebnisliste
  if (!Array.isArray(list)) return []
  const results: JobCard[] = []
  for (const entry of list) {
    try {
      const record = obj(entry)
      if (!record) continue
      const card = mapCard(record)
      if (card) results.push(card)
    } catch {
      continue
    }
  }
  return results
}

/** Total hits the API reports for the query, independent of page size. */
export function parseTotal(payload: unknown): number | null {
  return num(obj(payload)?.maxErgebnisse)
}

export function parseJobDetail(payload: unknown, fallbackId: string): JobDetail | null {
  const record = obj(payload)
  if (!record) return null
  // A detail record always carries a refnr and a title, but fall back rather
  // than throw if the portal ever serves one that does not.
  const card =
    mapCard(record) ??
    mapCard({
      ...record,
      referenznummer: str(record.referenznummer) ?? fallbackId,
      stellenangebotsTitel: "(ohne Titel)",
    })
  if (!card) return null
  return {
    ...card,
    description: cleanDescription(record.stellenangebotsBeschreibung),
    salary: formatSalary(record),
    temporaryAgency: bool(record.istArbeitnehmerUeberlassung),
    privatePlacement: bool(record.istPrivateArbeitsvermittlung),
    careerChangerFriendly: bool(record.quereinstiegGeeignet),
    // The detail endpoint 404s once a posting is withdrawn or expired, and a
    // 404 is surfaced as NOT_FOUND before we get here. A record that still
    // resolves is therefore live: this is "the portal still serves it", not a
    // separate status field — the API publishes none.
    isActive: true,
  }
}

/**
 * The API honours `veroeffentlichtseit` only for 1, 7, 14 and 28 days. Any other
 * value is silently ignored and the search returns every posting regardless of
 * age (measured 2026-10-26: 2, 3, 10, 21 and 30 all gave the unfiltered total).
 * So a requested window is rounded UP to the next honoured bucket; beyond 28
 * days there is no filter. Callers that need an exact window filter `date`.
 */
export const JOBAGE_BUCKETS = [1, 7, 14, 28]

export function jobageToVeroeffentlichtseit(days: number): string | null {
  if (!days || days <= 0 || days >= 9999) return null
  const bucket = JOBAGE_BUCKETS.find((b) => b >= days)
  return bucket === undefined ? null : String(bucket)
}

/** Map --offer-type to the portal's `angebotsart` code. */
export function offerTypeCode(mode: string | undefined): string | null {
  switch ((mode || "").toLowerCase()) {
    case "arbeit":
    case "job":
      return "1"
    case "selbststaendigkeit":
    case "selbstaendigkeit":
    case "freelance":
      return "2"
    case "ausbildung":
      return "4"
    case "praktikum":
    case "trainee":
      return "34"
    default:
      return null
  }
}

/** Map --worktime to the portal's `arbeitszeit` code. */
export function workTimeCode(mode: string | undefined): string | null {
  switch ((mode || "").toLowerCase()) {
    case "vollzeit":
    case "fulltime":
      return "vz"
    case "teilzeit":
    case "parttime":
      return "tz"
    case "schicht":
      return "snw"
    case "homeoffice":
    case "heimarbeit":
      return "ho"
    case "minijob":
      return "mj"
    default:
      return null
  }
}
