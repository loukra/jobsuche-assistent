// Live smoke tests against workwise.io. They make a handful of real requests —
// keep it that way; this is a job board, not a load-test target.
import { describe, expect, test } from "bun:test"
import { runCLI, parseJSON } from "./helpers.js"

// Live tests hit the real portal, so postings they pin go stale and CI breaks
// for reasons outside this code. They run only on demand: LIVE_SMOKE=1 bun test
const LIVE = process.env.LIVE_SMOKE === "1"

interface SearchResponse {
  meta: { count: number; page: number; pages: number | null; total: number | null; searchId: number }
  results: Array<{
    id: string
    title: string
    company: string | null
    location: string | null
    date: string | null
    remoteWork: string | null
    url: string
  }>
}

describe.skipIf(!LIVE)("search (live)", () => {
  test("returns real results with the contract's required fields", async () => {
    const result = await runCLI(["search", "-q", "Data Engineer", "--limit", "5"])
    expect(result.exitCode).toBe(0)
    const json = parseJSON<SearchResponse>(result)

    expect(json.meta).toBeDefined()
    expect(typeof json.meta.count).toBe("number")
    expect(json.meta.page).toBe(1)
    expect(Array.isArray(json.results)).toBe(true)
    expect(json.results.length).toBeGreaterThan(0)

    for (const job of json.results) {
      expect(job.id).toMatch(/^\d+$/)
      expect(job.title.length).toBeGreaterThan(0)
      expect(job.url).toStartWith("https://www.workwise.io/job/")
      // Contract: missing values are null, never omitted.
      for (const key of ["company", "location", "date"] as const) {
        expect(job).toHaveProperty(key)
      }
    }
  }, 60000)

  test("--limit caps the result count", async () => {
    const result = await runCLI(["search", "-q", "Softwareentwickler", "--limit", "3"])
    const json = parseJSON<SearchResponse>(result)
    expect(json.results.length).toBeLessThanOrEqual(3)
    expect(json.meta.count).toBe(json.results.length)
  }, 60000)

  // A location search returns jobs *at* that location plus jobs with no fixed
  // location, so "every result names the city" is not true and must not be
  // asserted — it passes only while the on-site matches happen to sort first.
  //
  // "No fixed location" is `location: null` and covers more than remote work:
  // travelling roles (Montage, site work) carry no locationLevels while still
  // reporting remoteWork "not_possible", so keying off remoteWork alone flakes
  // the moment one of those sorts into the page.
  const matchesLocationSearch = (job: SearchResponse["results"][number], city: string) =>
    job.location === null ||
    job.location.includes(city) ||
    job.remoteWork === "mandatory" ||
    job.remoteWork === "possible"

  test("--location narrows the result set", async () => {
    // The strongest available signal that the filter was applied at all: the
    // total must drop. The empty-city bug returned the full nationwide total
    // while looking like a normal, successful search.
    const nationwide = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "--limit", "1"]),
    )
    const berlin = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "-l", "Berlin", "--limit", "1"]),
    )
    expect(nationwide.meta.total).toBeGreaterThan(0)
    expect(berlin.meta.total).toBeGreaterThan(0)
    expect(berlin.meta.total!).toBeLessThan(nationwide.meta.total!)
  }, 60000)

  test("--location results are in that city or remote-capable", async () => {
    const result = await runCLI(["search", "-q", "Softwareentwickler", "-l", "Berlin"])
    const json = parseJSON<SearchResponse>(result)
    expect(json.results.length).toBeGreaterThan(0)
    for (const job of json.results) {
      expect(matchesLocationSearch(job, "Berlin")).toBe(true)
    }
  }, 60000)

  test("a lat,lon --location applies the radius, not a nationwide fallback", async () => {
    // Regression: an empty `city` in the location filter makes the API fall back
    // to limiter "country_code", quietly ignoring lat/lon and the radius. Berlin's
    // coordinates must behave like "Berlin", not like an unfiltered search.
    const coords = parseJSON<SearchResponse>(
      await runCLI([
        "search", "-q", "Softwareentwickler", "-l", "52.520008,13.404954", "--radius", "30",
      ]),
    )
    const named = parseJSON<SearchResponse>(
      await runCLI(["search", "-q", "Softwareentwickler", "-l", "Berlin", "--radius", "30"]),
    )
    expect(coords.meta.total).toBe(named.meta.total)
    for (const job of coords.results) {
      expect(matchesLocationSearch(job, "Berlin")).toBe(true)
    }
  }, 60000)

  test("--with-dates fills in the publication date the search API omits", async () => {
    const result = await runCLI([
      "search", "-q", "Softwareentwickler", "-l", "Berlin", "--limit", "3", "--with-dates",
    ])
    const json = parseJSON<SearchResponse>(result)
    expect(json.results.length).toBeGreaterThan(0)
    const dated = json.results.filter((j) => j.date !== null)
    expect(dated.length).toBeGreaterThan(0)
    for (const job of dated) {
      expect(Number.isNaN(Date.parse(job.date!))).toBe(false)
    }
  }, 90000)

  test("table format renders a header and rows", async () => {
    const result = await runCLI(["search", "-q", "Data Engineer", "--limit", "3", "--format", "table"])
    expect(result.exitCode).toBe(0)
    expect(result.stdout).toContain("TITLE")
    expect(result.stdout).toContain("COMPANY")
  }, 60000)
})

describe.skipIf(!LIVE)("detail (live)", () => {
  test("returns a readable description for a job found via search", async () => {
    const search = await runCLI(["search", "-q", "Data Engineer", "--limit", "1"])
    const json = parseJSON<SearchResponse>(search)
    const id = json.results[0]!.id

    const result = await runCLI(["detail", id, "--format", "plain"])
    expect(result.exitCode).toBe(0)
    expect(result.stdout.length).toBeGreaterThan(200)
    // Entities decoded and tags stripped.
    expect(result.stdout).not.toContain("&amp;")
    expect(result.stdout).not.toMatch(/<\/?(p|div|li|span)\b/)
    expect(result.stdout).toContain("URL: https://www.workwise.io/job/")
  }, 60000)

  test("json format carries the description and posting date", async () => {
    const result = await runCLI(["detail", "123632"])
    expect(result.exitCode).toBe(0)
    const job = parseJSON<{ id: string; title: string; description: string | null; date: string | null }>(result)
    expect(job.id).toBe("123632")
    expect(job.title.length).toBeGreaterThan(0)
    expect(job.description).not.toBeNull()
    expect(job.date).not.toBeNull()
  }, 60000)
})

describe("error handling", () => {
  const expectJSONError = (stderr: string, code: string) => {
    const parsed = JSON.parse(stderr) as { error: string; code: string }
    expect(parsed.code).toBe(code)
    expect(parsed.error.length).toBeGreaterThan(0)
  }

  test("a bogus flag exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["search", "-q", "test", "--not-a-flag", "1"])
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toBe("")
    expectJSONError(result.stderr, "UNKNOWN_FLAG")
  })

  test("detail without an id exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["detail"])
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toBe("")
    expectJSONError(result.stderr, "NO_ID")
  })

  test("an unparseable detail id exits 1 rather than fetching", async () => {
    const result = await runCLI(["detail", "not-a-job"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_ID")
  })

  test("an unknown location exits 1 and names the supported forms", async () => {
    const result = await runCLI(["search", "-q", "test", "-l", "Atlantis"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "UNKNOWN_LOCATION")
    expect(result.stderr).toContain("berlin")
  })

  test("a non-numeric --jobage exits 1", async () => {
    const result = await runCLI(["search", "-q", "test", "--jobage", "gestern"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_ARG")
  })

  test("an unsupported --remote mode is rejected, not silently ignored", async () => {
    const result = await runCLI(["search", "-q", "test", "--remote", "hybrid"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_ARG")
  })

  test("an unknown command exits 1", async () => {
    const result = await runCLI(["frobnicate"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_CMD")
  })
})
