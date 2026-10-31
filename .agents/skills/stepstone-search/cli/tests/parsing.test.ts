import { describe, expect, test } from "bun:test"
import {
  decodeHtmlEntities,
  detailUrl,
  htmlToText,
  parseJobCards,
  parseSalaries,
  parseJobDetail,
  parseRelativeDate,
  parseTotalCount,
  stripStyleAndScript,
  textAt,
} from "../src/helpers.js"
import { buildUrl, workFromHomeFlag } from "../src/commands/search.js"
import { normalizeId } from "../src/commands/detail.js"

// A minimal card in StepStone's real shape: hashed classes, an inline emotion
// <style> block inside the first card, and icon <span>s nested inside the
// company/location fields.
const CARD_HTML = `
<article class="res-rqk6ol" id="job-item-11713465" data-at="job-item">
  <style data-emotion="res m28og8">.res-m28og8{padding:16px;}</style>
  <h2><a class="res-xaz43y" href="/stellenangebote--Data-Engineer-inovex-GmbH--11713465-inline.html" data-at="job-item-title">
    <div class="res-kyg8or"><div class="res-ewgtgq">Data Engineer* / ML Engineer*</div></div>
  </a></h2>
  <span class="res-1bl90s9" data-at="job-item-company-name">
    <span class="res-215qah"><span class="res-8wkck8"><svg><path d="M3.7"/></svg></span></span>inovex GmbH
  </span>
  <span class="res-r5cg0x" data-at="job-item-location">
    <span class="res-8wkck8"><svg><path d="M9.9"/></svg></span>K&ouml;ln, M&uuml;nchen
  </span>
  <span class="res-9lmmub" data-at="job-item-timeago">vor 6 Tagen</span>
  <span class="res-r5cg0x" data-at="job-item-work-from-home">Teilweise Home-Office</span>
</article>
<article class="res-rqk6ol" id="job-item-14438124" data-at="job-item">
  <h2><a href="https://www.stepstone.de/stellenangebote--x--14438124-inline.html" data-at="job-item-title">
    <div>Data Platform Engineer</div>
  </a></h2>
  <span data-at="job-item-company-name">HMS Analytical Software GmbH</span>
  <span data-at="job-item-location">Heidelberg</span>
  <span data-at="job-item-timeago">Heute</span>
</article>`

const NOW = new Date("2026-08-31T12:00:00Z")

describe("parseJobCards", () => {
  const cards = parseJobCards(CARD_HTML, NOW)

  test("finds every card", () => {
    expect(cards.length).toBe(2)
  })

  test("extracts the contract fields", () => {
    expect(cards[0]).toMatchObject({
      id: "11713465",
      title: "Data Engineer* / ML Engineer*",
      company: "inovex GmbH",
      location: "Köln, München",
      date: "2026-08-25",
      workFromHome: "Teilweise Home-Office",
    })
  })

  test("does not leak inline CSS into text fields", () => {
    for (const c of cards) {
      expect(c.title).not.toContain("box-sizing")
      expect(c.company ?? "").not.toContain("padding")
    }
  })

  test("resolves relative hrefs to absolute URLs", () => {
    expect(cards[0].url).toBe(
      "https://www.stepstone.de/stellenangebote--Data-Engineer-inovex-GmbH--11713465-inline.html",
    )
    expect(cards[1].url.startsWith("https://www.stepstone.de/")).toBe(true)
  })

  test("emits null rather than omitting a missing field", () => {
    expect(cards[1]).toHaveProperty("workFromHome")
    expect(cards[1].workFromHome).toBeNull()
  })

  test("one malformed card does not break the rest", () => {
    const broken = `<article id="job-item-999" data-at="job-item"><span>no title</span></article>` + CARD_HTML
    expect(parseJobCards(broken, NOW).map((c) => c.id)).toEqual(["11713465", "14438124"])
  })
})

describe("textAt", () => {
  test("tracks tag depth past nested icon spans", () => {
    expect(textAt(`<span data-at="x"><span><span>i</span></span>value</span>`, "x")).toBe("i value")
  })

  test("returns null for an absent anchor", () => {
    expect(textAt(CARD_HTML, "job-item-salary")).toBeNull()
  })
})

describe("parseRelativeDate", () => {
  test.each([
    ["Heute", "2026-08-31"],
    ["Gestern", "2026-08-30"],
    ["vor 6 Tagen", "2026-08-25"],
    ["vor 1 Tag", "2026-08-30"],
    ["vor 2 Wochen", "2026-08-17"],
    ["vor 3 Stunden", "2026-08-31"],
    ["31.07.2026", "2026-07-31"],
  ])("%s -> %s", (input, expected) => {
    expect(parseRelativeDate(input, NOW)).toBe(expected)
  })

  test("passes an unrecognised string through instead of dropping it", () => {
    expect(parseRelativeDate("demnächst", NOW)).toBe("demnächst")
  })

  test("null stays null", () => {
    expect(parseRelativeDate(null, NOW)).toBeNull()
  })
})

describe("entity and markup handling", () => {
  test("decodes German entities and numeric refs", () => {
    expect(decodeHtmlEntities("M&uuml;nchen &#8211; Gru&szlig;e &#x26; mehr")).toBe("München – Gruße & mehr")
  })

  test("decodes the ampersand last so &amp;lt; stays literal", () => {
    expect(decodeHtmlEntities("&amp;lt;")).toBe("&lt;")
  })

  test("strips style and script blocks wholesale", () => {
    expect(stripStyleAndScript(`a<style>.x{color:red}</style>b<script>var y=1</script>c`).replace(/\s+/g, "")).toBe("abc")
  })

  test("htmlToText keeps list and paragraph structure", () => {
    const text = htmlToText("<p>Aufgaben</p><ul><li>Eins</li><li>Zwei</li></ul>")
    expect(text).toContain("Aufgaben")
    expect(text).toContain("• Eins")
    expect(text).toContain("• Zwei")
    expect(text).not.toContain("<")
  })
})

describe("parseTotalCount", () => {
  test.each(["&quot;searchResultsTotalJobCount&quot;:235", "&#34;searchResultsTotalJobCount&#34;:235"])(
    "reads the total through either quote escaping",
    (payload) => {
      expect(parseTotalCount(`x${payload},y`)).toBe(235)
    },
  )

  test("returns null when the payload is absent", () => {
    expect(parseTotalCount("<html></html>")).toBeNull()
  })
})

describe("parseJobDetail", () => {
  const LD = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: "Data Engineer (mwd)",
    url: "https://www.stepstone.de/stellenangebote--x--14438124-inline.html",
    datePosted: "2026-08-31T02:03:49.27Z",
    validThrough: "2026-09-30T01:39:06.277Z",
    employmentType: "FULL_TIME",
    industry: "IT, IT-Datenbanken",
    hiringOrganization: { name: "HMS Analytical Software GmbH", url: "https://www.stepstone.de/cmp/x" },
    jobLocation: { address: { addressLocality: "Heidelberg", addressRegion: "" } },
    description: "<p>Über uns</p><ul><li>Punkt eins</li></ul>",
  }
  const page = `<html><script type="application/ld+json">${JSON.stringify(LD)}</script></html>`

  test("maps JSON-LD onto the contract shape", () => {
    expect(parseJobDetail(page, "14438124")).toMatchObject({
      id: "14438124",
      title: "Data Engineer (mwd)",
      company: "HMS Analytical Software GmbH",
      location: "Heidelberg",
      date: "2026-08-31",
      validThrough: "2026-09-30",
      employmentType: "FULL_TIME",
    })
  })

  test("skips an unparseable block and still finds a later valid one", () => {
    const noisy = `<script type="application/ld+json">{ not json }</script>` + page
    expect(parseJobDetail(noisy, "14438124")?.title).toBe("Data Engineer (mwd)")
  })

  test("finds a JobPosting nested in an @graph", () => {
    const graph = `<script type="application/ld+json">${JSON.stringify({ "@graph": [{ "@type": "WebPage" }, LD] })}</script>`
    expect(parseJobDetail(graph, "14438124")?.company).toBe("HMS Analytical Software GmbH")
  })

  test("returns null when no JobPosting is present", () => {
    expect(parseJobDetail("<html>nothing here</html>", "1")).toBeNull()
  })
})

describe("buildUrl", () => {
  const base = { page: 1, format: "json" } as const

  test("maps query and location onto q/where", () => {
    const u = new URL(buildUrl({ ...base, query: "Data Engineer", location: "Berlin" }))
    expect(u.searchParams.get("q")).toBe("Data Engineer")
    expect(u.searchParams.get("where")).toBe("Berlin")
  })

  test("maps --jobage onto the ag=age_<days> facet", () => {
    expect(new URL(buildUrl({ ...base, query: "x", jobage: 14 })).searchParams.get("ag")).toBe("age_14")
  })

  test("omits ag when no age filter is requested", () => {
    expect(new URL(buildUrl({ ...base, query: "x" })).searchParams.get("ag")).toBeNull()
  })

  test("omits page=1 and sets it from page 2 on", () => {
    expect(new URL(buildUrl({ ...base, query: "x" })).searchParams.get("page")).toBeNull()
    expect(new URL(buildUrl({ ...base, query: "x", page: 3 })).searchParams.get("page")).toBe("3")
  })

  test("maps the work-from-home modes", () => {
    expect(workFromHomeFlag("remote")).toBe("2")
    expect(workFromHomeFlag("hybrid")).toBe("1")
    expect(workFromHomeFlag(undefined)).toBeNull()
  })
})

describe("normalizeId", () => {
  test.each([
    ["11713465", "11713465"],
    ["https://www.stepstone.de/stellenangebote--Data-Engineer-inovex--11713465-inline.html", "11713465"],
    ["https://www.stepstone.de/stellenangebote--x--14438124-inline.html", "14438124"],
  ])("%s -> %s", (input, expected) => {
    expect(normalizeId(input)).toBe(expected)
  })

  test("rejects input with no id", () => {
    expect(normalizeId("not-a-job")).toBeNull()
  })
})

describe("detailUrl", () => {
  test("builds a slug-free detail URL from a bare id", () => {
    expect(detailUrl("123456")).toBe("https://www.stepstone.de/stellenangebote--x--123456-inline.html")
  })
})

describe("parseSalaries", () => {
  // Shape of the inline JSON on a search page (2026-10-29), shortened.
  const page =
    '{"url":"https://www.stepstone.de/stellenangebote--Dev-Hamburg-Acme--14631291-inline.html?rltr=1","companyName":"Acme",' +
    '"unifiedSalary":{"salaryType":"Predicted","salaryAvailable":true,"exactValue":null,"min":39000,"max":56000,"period":"Annually","currency":"€"}},' +
    '{"url":"https://www.stepstone.de/stellenangebote--Lead-Beta--14000001-inline.html","companyName":"Beta",' +
    '"unifiedSalary":{"salaryType":"Exact","salaryAvailable":true,"exactValue":null,"min":4500,"max":5500,"period":"Monthly","currency":"€"}},' +
    '{"url":"https://www.stepstone.de/stellenangebote--Ops-Gamma--14000002-inline.html",' +
    '"unifiedSalary":{"salaryType":null,"salaryAvailable":false,"exactValue":null,"min":null,"max":null}}'

  test("labels StepStone's own estimate and keeps the period", () => {
    const s = parseSalaries(page)
    expect(s.get("14631291")).toBe("39000–56000 € (StepStone-Schätzung)")
    expect(s.get("14000001")).toBe("4500–5500 € monatlich")
    expect(s.has("14000002")).toBe(false)
  })

  test("reads the HTML-escaped variant of the payload", () => {
    expect(parseSalaries(page.replace(/"/g, "&quot;")).get("14631291")).toBe("39000–56000 € (StepStone-Schätzung)")
  })
})
