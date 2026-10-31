import { fetchDetail, fetchJobIndex, hexId, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/**
 * Accept a full posting URL, a bare slug, or just the 12-hex id. The hex form
 * needs a sitemap lookup because the detail URL requires the whole slug.
 */
async function normalizeSlug(input: string): Promise<string | null> {
  const trimmed = input.trim()
  const fromUrl = trimmed.match(/\/(?:de|en)\/job\/([^/?#]+)/)
  if (fromUrl) return fromUrl[1]
  if (/^[0-9a-f]{12}$/i.test(trimmed)) {
    const hex = trimmed.toLowerCase()
    const index = await fetchJobIndex()
    return index.find((e) => hexId(e.slug) === hex)?.slug ?? null
  }
  if (/^[a-z0-9-]+-[0-9a-f]{12}$/i.test(trimmed)) return trimmed
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  let slug: string | null
  try {
    slug = await normalizeSlug(opts.id)
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
  if (!slug) {
    writeError(
      `Could not resolve "${opts.id}" to an Instaffo posting — pass the id from search results, a 12-hex id, or a full jobs.instaffo.com/de/job/... URL`,
      "BAD_ID",
    )
    return 1
  }
  try {
    const job = await fetchDetail(slug)
    if (!job) {
      writeError("Job not found (it may have been taken down)", "NOT_FOUND")
      return 1
    }
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${[job.location, job.postalCode].filter(Boolean).join(" ") || "—"}`,
        "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        job.date ? `Posted: ${job.date}` : "",
        job.validThrough ? `Valid through: ${job.validThrough}` : "",
        `Status: ${job.isActive ? "ACTIVE" : "EXPIRED"}`,
        "",
        job.description || "(no description)",
        "",
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
