import { describe, expect, test } from "bun:test"
import { runCLI, parseJSON } from "./helpers"

// Live tests hit the real portal, so postings they pin go stale and CI breaks
// for reasons outside this code. They run only on demand: LIVE_SMOKE=1 bun test
const LIVE = process.env.LIVE_SMOKE === "1"

interface SearchResponse {
  meta: { count: number; page: number; total: number | null }
  results: Array<{
    id: string
    title: string
    company: string | null
    location: string | null
    date: string | null
    url: string
  }>
}

describe.skipIf(!LIVE)("search (live)", () => {
  test("returns real results for a German-language query", async () => {
    const result = await runCLI(["search", "-q", "Softwareentwickler", "-l", "Hamburg", "--limit", "5"])
    expect(result.exitCode).toBe(0)
    const data = parseJSON<SearchResponse>(result)

    expect(data.results.length).toBeGreaterThan(0)
    expect(data.results.length).toBeLessThanOrEqual(5)
    expect(data.meta.page).toBe(1)
    expect(data.meta.count).toBe(data.results.length)

    for (const job of data.results) {
      expect(job.id).toBeTruthy()
      expect(job.title).toBeTruthy()
      expect(job.url).toStartWith("https://www.arbeitsagentur.de/jobsuche/jobdetail/")
      // Every documented key is present, null rather than omitted when unknown.
      for (const key of ["company", "location", "date", "region", "profession"]) {
        expect(job).toHaveProperty(key)
      }
    }
  })

  test("table format renders a header and rows", async () => {
    const result = await runCLI([
      "search", "-q", "Softwareentwickler", "-l", "Hamburg", "--limit", "3", "--format", "table",
    ])
    expect(result.exitCode).toBe(0)
    expect(result.stdout).toContain("TITEL")
    expect(result.stdout).toContain("FIRMA")
  })

  test("--jobage narrows the result set", async () => {
    const all = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "-l", "Hamburg", "--limit", "1"]),
    )
    const recent = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "-l", "Hamburg", "--jobage", "7", "--limit", "1"]),
    )
    expect(all.meta.total).not.toBeNull()
    expect(recent.meta.total).not.toBeNull()
    expect(recent.meta.total!).toBeLessThanOrEqual(all.meta.total!)
  })
})

describe.skipIf(!LIVE)("detail (live)", () => {
  test("returns a readable description for a posting from search", async () => {
    const search = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "-l", "Hamburg", "--limit", "1"]),
    )
    const id = search.results[0]!.id

    const result = await runCLI(["detail", id])
    expect(result.exitCode).toBe(0)
    const job = parseJSON<{ id: string; title: string; description: string | null; isActive: boolean }>(result)
    expect(job.id).toBe(id)
    expect(job.title).toBeTruthy()
    expect(job.isActive).toBe(true)
    if (job.description) {
      expect(job.description).not.toContain("<p>")
      expect(job.description).not.toContain("&amp;")
    }
  })

  test("a bogus reference number exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["detail", "99999-nichtvorhanden-S"])
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toBe("")
    const err = JSON.parse(result.stderr)
    expect(err.code).toBe("NOT_FOUND")
  })
})
