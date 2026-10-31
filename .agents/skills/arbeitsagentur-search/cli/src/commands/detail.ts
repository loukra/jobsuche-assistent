import { DETAIL_URL, encodeRefnr, jsonFetch, parseJobDetail, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/**
 * Accept a raw reference number (`13644-311617-S`), a jobdetail URL, or the
 * base64url form the detail endpoint itself uses.
 */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null

  const fromUrl = trimmed.match(/\/jobsuche\/jobdetail\/([^/?#]+)/)
  const candidate = fromUrl ? decodeURIComponent(fromUrl[1]) : trimmed

  // A refnr always contains a hyphen and no base64url padding characters.
  if (/^[0-9A-Za-z][0-9A-Za-z._+()/-]*-[0-9A-Za-z._+()/-]*$/.test(candidate) && candidate.includes("-")) {
    return candidate
  }
  // Otherwise try to read it as base64url of a refnr.
  try {
    const decoded = Buffer.from(candidate, "base64url").toString("utf8")
    if (/^[\x20-\x7e]+$/.test(decoded) && decoded.includes("-")) return decoded
  } catch {
    /* fall through */
  }
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const refnr = normalizeId(opts.id)
  if (!refnr) {
    writeError(`Could not parse a reference number from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const payload = await jsonFetch(`${DETAIL_URL}/${encodeRefnr(refnr)}`)
    if (payload === null) {
      writeError(
        `Job ${refnr} not found — the posting was withdrawn, expired, or the reference number is wrong`,
        "NOT_FOUND",
      )
      return 1
    }
    const job = parseJobDetail(payload, refnr)
    if (!job) {
      writeError(`Unexpected response shape for job ${refnr}`, "PARSE_FAILED")
      return 1
    }

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}`,
        "",
        job.offerType ? `Angebotsart: ${job.offerType}` : "",
        job.profession ? `Beruf: ${job.profession}` : "",
        // The API exposes a Vollzeit flag, not a full working-time model, so
        // report the flag rather than inferring "Teilzeit" from its absence.
        job.fulltime === null ? "" : `Vollzeit: ${job.fulltime ? "ja" : "nein"}`,
        job.contractDuration ? `Vertragsdauer: ${job.contractDuration}` : "",
        job.entryDate ? `Eintritt: ${job.entryDate}` : "",
        job.salary ? `Vergütung: ${job.salary}` : "",
        job.homeoffice === null ? "" : `Homeoffice: ${job.homeoffice ? "ja" : "nein"}`,
        job.temporaryAgency ? "Hinweis: Arbeitnehmerüberlassung" : "",
        job.privatePlacement ? "Hinweis: private Arbeitsvermittlung" : "",
        job.date ? `Veröffentlicht: ${job.date}` : "",
        "",
        job.description || "(keine Beschreibung)",
        "",
        job.externalUrl ? `Externe Anzeige: ${job.externalUrl}` : "",
        `URL: ${job.url}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
