import { fetchPage, jobUrl, parseJobDetail, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/**
 * Accept a raw enquiry id or any Workwise job URL. `/job/<id>` 301-redirects to
 * the canonical `/job/<id>-<slug>`, so the slug is optional everywhere.
 */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  const bare = trimmed.match(/^\d{2,}$/)
  if (bare) return trimmed
  const fromUrl = trimmed.match(/\/job\/(\d+)/)
  if (fromUrl) return fromUrl[1]!
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(
      `could not parse a job id from "${opts.id}" - pass a numeric id or a workwise.io/job/... URL`,
      "BAD_ID",
    )
    return 1
  }
  try {
    const html = await fetchPage(jobUrl(id))
    if (!html) {
      writeError("job not found", "NOT_FOUND")
      return 1
    }
    const job = parseJobDetail(html, id)
    if (!job) {
      writeError("could not parse the job page (portal markup may have changed)", "PARSE_FAILED")
      return 1
    }

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}`,
        "",
        job.date ? `Veröffentlicht: ${job.date.slice(0, 10)}` : "",
        job.validThrough ? `Gültig bis: ${job.validThrough.slice(0, 10)}` : "",
        job.employmentType ? `Anstellungsart: ${job.employmentType}` : "",
        job.hoursPerWeek ? `Stunden: ${job.hoursPerWeek}` : "",
        job.salary ? `Gehalt: ${job.salary}` : "",
        job.remoteWork ? `Remote: ${job.remoteWork}` : "",
        job.occupationalCategory ? `Kategorie: ${job.occupationalCategory}` : "",
        job.skills ? `Skills: ${job.skills}` : "",
        job.status ? `Status: ${job.status}` : "",
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
