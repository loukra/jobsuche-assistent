import { describe, expect, test } from "bun:test"
import { parseJSON, runCLI } from "./helpers.js"

// Live tests hit the real portal, so postings they pin go stale and CI breaks
// for reasons outside this code. They run only on demand: LIVE_SMOKE=1 bun test
const LIVE = process.env.LIVE_SMOKE === "1"

// Hits StepStone for real. Keep this file small - it is a smoke test, not a crawl.
interface SearchResponse {
  meta: { count: number; page: number; total: number | null }
  results: {
    id: string
    title: string
    company: string | null
    location: string | null
    date: string | null
    url: string
  }[]
}

describe.skipIf(!LIVE)("live search", () => {
  test("returns real, fully populated results", async () => {
    const data = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Data Engineer", "-l", "Berlin", "--limit", "5"]),
    )

    expect(data.meta.page).toBe(1)
    expect(data.results.length).toBeGreaterThan(0)
    expect(data.meta.count).toBe(data.results.length)

    for (const job of data.results) {
      expect(job.id).toMatch(/^\d+$/)
      expect(job.title.length).toBeGreaterThan(0)
      expect(job.title).not.toContain("<")
      expect(job.url).toStartWith("https://www.stepstone.de/")
      // Missing values must be null, never omitted.
      for (const key of ["company", "location", "date"] as const) {
        expect(job).toHaveProperty(key)
      }
    }
  })

  test("--limit caps the result count", async () => {
    const data = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Software", "-l", "Hamburg", "--limit", "2"]),
    )
    expect(data.results.length).toBeLessThanOrEqual(2)
  })

  test("detail on a live search hit returns readable text", async () => {
    const search = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Data Engineer", "-l", "Berlin", "--limit", "1"]),
    )
    const id = search.results[0].id

    const detail = parseJSON<{ id: string; title: string; description: string | null }>(
      await runCLI(["detail", id]),
    )
    expect(detail.id).toBe(id)
    expect(detail.title.length).toBeGreaterThan(0)
    expect(detail.description ?? "").not.toContain("<p>")
    expect((detail.description ?? "").length).toBeGreaterThan(100)
  })
})
