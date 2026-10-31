import { describe, expect, test } from "bun:test"
import { parseJSON, runCLI } from "./helpers.js"

// Live tests hit the real portal, so postings they pin go stale and CI breaks
// for reasons outside this code. They run only on demand: LIVE_SMOKE=1 bun test
const LIVE = process.env.LIVE_SMOKE === "1"

interface SearchResponse {
  meta: { count: number; page: number; source: string; category: string | null }
  results: { id: string; title: string; company: string | null; location: string | null; date: string | null; url: string }[]
}

describe.skipIf(!LIVE)("search (live)", () => {
  test("returns real, fully-populated results for a role query", async () => {
    const res = await runCLI(["search", "-q", "softwareentwickler", "--limit", "3"])
    const data = parseJSON<SearchResponse>(res)

    expect(data.results.length).toBeGreaterThan(0)
    for (const job of data.results) {
      expect(job.id).toBeTruthy()
      expect(job.title).toBeTruthy()
      expect(job.url).toStartWith("https://jobs.instaffo.com/de/job/")
      // Hydration must actually run — id/title/url alone would mean the detail
      // pass silently failed and the caller gets uselessly bare cards.
      expect(job.company).toBeTruthy()
    }
  }, 120_000)

  test("uses the location-qualified category page when one exists", async () => {
    const data = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "backend entwickler", "-l", "Berlin", "--limit", "3"]),
    )
    expect(data.meta.source).toBe("category")
    expect(data.meta.category).toBe("backend-entwickler-berlin")
  }, 120_000)

  test("a city that has no category page falls back to the sitemap", async () => {
    // Flensburg has no category page and usually no posting at all, so this
    // exercises the sitemap fallback plus the post-hydration location filter.
    // It is the case that a naive category-only search gets wrong. Zero results
    // are a valid answer; any result must really be located there.
    const data = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "finanzbuchhalter", "-l", "Flensburg", "--limit", "3"]),
    )
    expect(data.meta.source).toBe("sitemap")
    for (const job of data.results) expect(job.location).toContain("Flensburg")
  }, 120_000)

  test("respects --limit", async () => {
    const data = parseJSON<SearchResponse>(await runCLI(["search", "-q", "data engineer", "--limit", "2"]))
    expect(data.results.length).toBeLessThanOrEqual(2)
  }, 120_000)
})

describe.skipIf(!LIVE)("detail (live)", () => {
  test("returns a readable description for a job found by search", async () => {
    const search = parseJSON<SearchResponse>(await runCLI(["search", "-q", "softwareentwickler", "--limit", "1"]))
    const id = search.results[0].id

    const job = parseJSON<{ id: string; title: string; description: string; url: string }>(
      await runCLI(["detail", id]),
    )
    expect(job.id).toBe(id)
    expect(job.title).toBeTruthy()
    expect(job.description.length).toBeGreaterThan(50)
    expect(job.description).not.toContain("<p>")
    expect(job.description).not.toContain("&amp;")
  }, 120_000)

  test("resolves a bare 12-hex id via the sitemap", async () => {
    const job = parseJSON<{ id: string; company: string }>(await runCLI(["detail", "740946f4ab7d"]))
    expect(job.id).toBe("finanzbuchhalter-m-w-d-740946f4ab7d")
  }, 120_000)

  test("accepts a full posting URL", async () => {
    const job = parseJSON<{ id: string }>(
      await runCLI(["detail", "https://jobs.instaffo.com/de/job/finanzbuchhalter-m-w-d-740946f4ab7d"]),
    )
    expect(job.id).toBe("finanzbuchhalter-m-w-d-740946f4ab7d")
  }, 120_000)
})

describe("error contract", () => {
  const expectJSONError = (res: { stdout: string; stderr: string; exitCode: number }, code: string) => {
    expect(res.exitCode).toBe(1)
    expect(res.stdout).toBe("") // errors never go to stdout
    expect(JSON.parse(res.stderr)).toMatchObject({ code, error: expect.any(String) })
  }

  test("rejects an unknown flag instead of silently ignoring it", async () => {
    expectJSONError(await runCLI(["search", "-q", "data", "--bogus", "x"]), "UNKNOWN_FLAG")
  })

  test("requires at least one search criterion", async () => {
    expectJSONError(await runCLI(["search"]), "NO_CRITERIA")
  })

  test("rejects a non-numeric --limit", async () => {
    expectJSONError(await runCLI(["search", "-q", "data", "--limit", "abc"]), "BAD_ARG")
  })

  test("requires an id for detail", async () => {
    expectJSONError(await runCLI(["detail"]), "NO_ID")
  })

  test("rejects an unparseable detail id", async () => {
    expectJSONError(await runCLI(["detail", "not a real id"]), "BAD_ID")
  })

  test("rejects an unknown command", async () => {
    expectJSONError(await runCLI(["frobnicate"]), "BAD_CMD")
  })
})
