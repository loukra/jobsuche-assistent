import { describe, expect, test } from "bun:test"
import {
  buildFilters,
  decodeHtmlEntities,
  geocode,
  htmlToText,
  jobUrl,
  mapMatching,
  parseDatePosted,
  parseJobDetail,
  parseJsonLd,
  remoteWorkFlag,
} from "../src/helpers.js"
import { normalizeId } from "../src/commands/detail.js"

describe("buildFilters", () => {
  test("sends every key the API requires, even when unset", () => {
    // A partial body is rejected with "Search Api Validation Error", so the
    // full default filter object has to go out on every request.
    const filters = buildFilters({ query: "Data Engineer" })
    for (const key of [
      "description", "end", "hoursEnd", "hoursStart", "languageLevels",
      "leadershipExperience", "locationLevels", "mobileWork", "occupations",
      "ongoing", "remoteWork", "salary", "salaryFlexible", "salaryType",
      "searchCompanyLevels", "searchCompanyTagLevels", "searchesEnquiryTypes",
      "start", "workExperience", "worldwide",
    ]) {
      expect(filters).toHaveProperty(key)
    }
    expect(filters.description).toBe("Data Engineer")
    expect(filters.remoteWork).toBe("does_not_matter")
    expect(filters.locationLevels).toEqual([])
  })

  test("an omitted query becomes an empty description, not undefined", () => {
    expect(buildFilters({}).description).toBe("")
  })
})

describe("geocode", () => {
  test("resolves a known city and puts the radius in `level`", () => {
    const geo = geocode("Berlin", 30)
    expect(geo).not.toBeNull()
    expect(geo!.location.lat).toBeCloseTo(52.52, 2)
    expect(geo!.location.lon).toBeCloseTo(13.4, 2)
    // The API reuses `level` for the search radius in km.
    expect(geo!.location.level).toBe(30)
    expect(geo!.location.countryCode).toBe("DE")
  })

  test("is case-insensitive and accepts transliterated umlauts", () => {
    expect(geocode("münchen", 25)!.location.lat).toBeCloseTo(48.135, 2)
    expect(geocode("Muenchen", 25)!.location.lat).toBeCloseTo(48.135, 2)
    expect(geocode("MÜNCHEN", 25)!.location.lat).toBeCloseTo(48.135, 2)
  })

  test("accepts an explicit lat,lon pair for cities not in the table", () => {
    const geo = geocode("51.2277,6.7734", 15)
    expect(geo).not.toBeNull()
    expect(geo!.location.lat).toBeCloseTo(51.2277, 3)
    expect(geo!.location.lon).toBeCloseTo(6.7734, 3)
    expect(geo!.location.level).toBe(15)
  })

  test("never emits an empty city, which would silently drop the radius", () => {
    // The API derives its `limiter` from the populated fields: an empty `city`
    // yields limiter "country_code" and returns nationwide results, ignoring
    // lat/lon and the radius entirely.
    for (const input of ["Berlin", "51.2277,6.7734", "-33.86,151.2"]) {
      const geo = geocode(input, 20)
      expect(geo).not.toBeNull()
      expect(geo!.location.city.length).toBeGreaterThan(0)
    }
  })

  test("returns null for an unknown place", () => {
    expect(geocode("Atlantis", 30)).toBeNull()
  })

  test("covers the Bremen / north-west Lower Saxony cluster", () => {
    for (const city of ["Bremen", "Oldenburg", "Bremerhaven", "Delmenhorst", "Wilhelmshaven"]) {
      expect(geocode(city, 30)).not.toBeNull()
    }
  })

  test("Oldenburg resolves to Oldenburg (Oldb), not Oldenburg in Holstein", () => {
    // Two German cities share the name. The Lower Saxony one (~170k, next to
    // Bremen) is the one a job search means; Holstein's is at 54.29/10.89.
    const geo = geocode("Oldenburg", 30)!
    expect(geo.location.lat).toBeCloseTo(53.14, 1)
    expect(geo.location.lon).toBeCloseTo(8.21, 1)
    expect(geo.location.state).toBe("Niedersachsen")
  })
})

describe("remoteWorkFlag", () => {
  test("maps user-facing modes to API values", () => {
    expect(remoteWorkFlag("remote")).toBe("entirely_wanted")
    expect(remoteWorkFlag("onsite")).toBe("not_wanted")
    expect(remoteWorkFlag("on-site")).toBe("not_wanted")
    expect(remoteWorkFlag(undefined)).toBe("does_not_matter")
  })

  test("returns null for an unsupported mode so the CLI can reject it", () => {
    expect(remoteWorkFlag("hybrid")).toBeNull()
    expect(remoteWorkFlag("nonsense")).toBeNull()
  })
})

describe("mapMatching", () => {
  const matching = {
    score: 40.63,
    enquiries: {
      id: 110689,
      name: "Data Engineer (m/w/d)",
      slug: "data-engineer-m-w-d",
      shortDescription: "Kurzbeschreibung",
      minSalary: "1500.00",
      maxSalary: "1800.00",
      hoursStart: 40,
      hoursEnd: 40,
      remoteWork: "not_possible",
      isEnquiryNew: true,
      type: { name: "Festanstellung" },
      company: { name: "SkelTech GmbH", slug: "skeltech-gmbh" },
      locationLevels: [{ city: "Frechen", state: "Nordrhein-Westfalen", country: "Deutschland" }],
    },
  }

  test("maps the API shape onto the portal-skill contract fields", () => {
    const job = mapMatching(matching)
    expect(job.id).toBe("110689")
    expect(job.title).toBe("Data Engineer (m/w/d)")
    expect(job.company).toBe("SkelTech GmbH")
    expect(job.location).toBe("Frechen")
    expect(job.url).toBe("https://www.workwise.io/job/110689-data-engineer-m-w-d")
    expect(job.salary).toBe("1500–1800 €")
    expect(job.hoursPerWeek).toBe("40 h")
    expect(job.isNew).toBe(true)
  })

  test("date is null from search - the API carries no posting date", () => {
    expect(mapMatching(matching).date).toBeNull()
  })

  test("missing values are null, never omitted", () => {
    const sparse = mapMatching({ enquiries: { id: 1, name: "X" } })
    for (const key of ["company", "location", "date", "employmentType", "salary"] as const) {
      expect(sparse).toHaveProperty(key)
      expect(sparse[key]).toBeNull()
    }
  })

  test("collapses a long location list instead of emitting a wall of cities", () => {
    const job = mapMatching({
      enquiries: {
        id: 2,
        name: "X",
        locationLevels: [
          { city: "Berlin" }, { city: "Hamburg" }, { city: "Köln" },
          { city: "München" }, { city: "Leipzig" },
        ],
      },
    })
    expect(job.location).toBe("Berlin, Hamburg, Köln +2")
  })
})

describe("normalizeId", () => {
  test("accepts a bare numeric id", () => {
    expect(normalizeId("110689")).toBe("110689")
  })

  test("accepts canonical and slugless job URLs", () => {
    expect(normalizeId("https://www.workwise.io/job/110689")).toBe("110689")
    expect(normalizeId("https://www.workwise.io/job/110689-data-engineer-m-w-d")).toBe("110689")
  })

  test("rejects input with no id in it", () => {
    expect(normalizeId("not-a-job")).toBeNull()
    expect(normalizeId("https://www.workwise.io/jobsuche")).toBeNull()
  })
})

describe("jobUrl", () => {
  test("omits the slug when absent - /job/<id> 301s to the canonical URL", () => {
    expect(jobUrl(110689)).toBe("https://www.workwise.io/job/110689")
    expect(jobUrl(110689, "abc")).toBe("https://www.workwise.io/job/110689-abc")
  })
})

describe("decodeHtmlEntities", () => {
  test("decodes named, decimal, and hex references", () => {
    expect(decodeHtmlEntities("Daten &amp; KI")).toBe("Daten & KI")
    expect(decodeHtmlEntities("K&#246;ln")).toBe("Köln")
    expect(decodeHtmlEntities("K&#xF6;ln")).toBe("Köln")
    expect(decodeHtmlEntities("f&#252;r")).toBe("für")
  })

  test("decodes &amp; last, so &amp;lt; does not collapse into a tag", () => {
    expect(decodeHtmlEntities("&amp;lt;script&amp;gt;")).toBe("&lt;script&gt;")
  })

  test("drops out-of-range code points instead of throwing", () => {
    expect(() => decodeHtmlEntities("&#9999999999;")).not.toThrow()
  })
})

describe("htmlToText", () => {
  test("keeps list items as bullets and preserves paragraph breaks", () => {
    const text = htmlToText("<p>Aufgaben</p><ul><li>Pipelines bauen</li><li>SQL &amp; Python</li></ul>")
    expect(text).toContain("• Pipelines bauen")
    expect(text).toContain("• SQL & Python")
    expect(text).not.toContain("<")
  })

  test("collapses runaway blank lines", () => {
    expect(htmlToText("<p>A</p><p></p><p></p><p>B</p>")).toBe("A\n\nB")
  })
})

describe("parseJsonLd / parseDatePosted", () => {
  const page = `<html><head>
    <script type="application/ld+json">{"@context":"https://schema.org/","@type":"BreadcrumbList","itemListElement":[]}</script>
    <script type="application/ld+json">{"@context":"https://schema.org/","@type":"JobPosting","title":"Data Engineer","datePosted":"2026-05-27T09:00:00+02:00","employmentType":["FULL_TIME"],"hiringOrganization":{"name":"rheindata GmbH"}}</script>
    </head></html>`

  test("picks the JobPosting block, not the first ld+json on the page", () => {
    const ld = parseJsonLd(page)
    expect(ld?.title).toBe("Data Engineer")
    expect(ld?.hiringOrganization?.name).toBe("rheindata GmbH")
  })

  test("a malformed ld+json block does not abort the scan", () => {
    const broken = `<script type="application/ld+json">{not json}</script>` + page
    expect(parseJsonLd(broken)?.title).toBe("Data Engineer")
  })

  test("reads datePosted for cheap date enrichment", () => {
    expect(parseDatePosted(page)).toBe("2026-05-27T09:00:00+02:00")
  })

  test("returns null when the page carries no JobPosting", () => {
    expect(parseJsonLd("<html><head></head></html>")).toBeNull()
    expect(parseDatePosted("<html></html>")).toBeNull()
  })
})

describe("parseJobDetail", () => {
  test("merges __NEXT_DATA__ and JSON-LD, preferring the richer enquiry", () => {
    const html = `
      <script type="application/ld+json">{"@type":"JobPosting","title":"LD Title","datePosted":"2026-05-27T09:00:00+02:00","validThrough":"2026-10-27T00:00:00.000Z","skills":"SQL | Fortgeschritten","directApply":true,"hiringOrganization":{"name":"LD Corp","sameAs":"http://example.com"}}</script>
      <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"enquiry":{"id":123632,"name":"Data Engineer (m/w/d)","slug":"data-engineer","status":"open","description":"<p>Aufgaben</p><ul><li>ETL</li></ul>","firstPublished":"2026-05-27T09:00:00+02:00","hoursStart":40,"hoursEnd":40,"type":{"name":"Festanstellung"},"company":{"name":"rheindata GmbH"},"locationLevels":[{"city":"Köln"}]}}}}</script>`
    const job = parseJobDetail(html, "123632")
    expect(job).not.toBeNull()
    expect(job!.title).toBe("Data Engineer (m/w/d)")
    expect(job!.company).toBe("rheindata GmbH")
    expect(job!.location).toBe("Köln")
    expect(job!.date).toBe("2026-05-27T09:00:00+02:00")
    expect(job!.employmentType).toBe("Festanstellung")
    expect(job!.description).toContain("• ETL")
    // JSON-LD-only fields still come through.
    expect(job!.skills).toBe("SQL | Fortgeschritten")
    expect(job!.validThrough).toBe("2026-10-27T00:00:00.000Z")
    expect(job!.companyUrl).toBe("http://example.com")
  })

  test("falls back to JSON-LD alone when __NEXT_DATA__ has no enquiry", () => {
    const html = `<script type="application/ld+json">{"@type":"JobPosting","title":"Nur LD","datePosted":"2026-01-02T00:00:00Z","employmentType":["FULL_TIME","OTHER"],"description":"<p>Text</p>","hiringOrganization":{"name":"ACME"},"jobLocation":[{"address":{"addressLocality":"Hamburg"}}]}</script>`
    const job = parseJobDetail(html, "1")
    expect(job!.title).toBe("Nur LD")
    expect(job!.company).toBe("ACME")
    expect(job!.location).toBe("Hamburg")
    expect(job!.employmentType).toBe("FULL_TIME, OTHER")
  })

  test("returns null when the page carries neither payload", () => {
    expect(parseJobDetail("<html><body>nope</body></html>", "1")).toBeNull()
  })
})
