import { describe, expect, test } from "bun:test"
import { hexId, parseItemList, parseJobPosting, resolveCategory, slugify, tokens } from "../src/helpers.js"

describe("slugify", () => {
  test("transliterates umlauts the way Instaffo spells its own slugs", () => {
    // A plain accent-strip would give "munchen"/"dusseldorf", which are not
    // real category slugs — the portal uses the ue/oe/ae expansion.
    expect(slugify("München")).toBe("muenchen")
    expect(slugify("Düsseldorf")).toBe("duesseldorf")
    expect(slugify("Köln")).toBe("koeln")
    expect(slugify("Nürnberg")).toBe("nuernberg")
    expect(slugify("Weiß")).toBe("weiss")
  })

  test("collapses punctuation and whitespace to single hyphens", () => {
    expect(slugify("Backend Entwickler")).toBe("backend-entwickler")
    expect(slugify("  C++  Developer (m/w/d) ")).toBe("c-developer-m-w-d")
  })

  test("drops one-character noise from match tokens", () => {
    expect(tokens("data engineer")).toEqual(["data", "engineer"])
    expect(tokens("a data")).toEqual(["data"])
  })
})

describe("hexId", () => {
  test("extracts the trailing 12-hex id from a slug or URL", () => {
    expect(hexId("finanzbuchhalter-m-w-d-740946f4ab7d")).toBe("740946f4ab7d")
    expect(hexId("https://jobs.instaffo.com/de/job/product-owner-m-w-d-9e5b1694cbe0")).toBe("9e5b1694cbe0")
  })

  test("returns null when there is no id", () => {
    expect(hexId("backend-entwickler-berlin")).toBeNull()
  })
})

describe("resolveCategory", () => {
  const slugs = ["backend-entwickler", "backend-entwickler-berlin", "data-jobs", "berlin"]

  test("prefers the location-qualified category", () => {
    expect(resolveCategory(slugs, "backend entwickler", "Berlin")).toBe("backend-entwickler-berlin")
  })

  test("falls back to the bare role category when the city has no page", () => {
    expect(resolveCategory(slugs, "backend entwickler", "Flensburg")).toBe("backend-entwickler")
  })

  test("returns null when nothing matches, sending the caller to the sitemap", () => {
    expect(resolveCategory(slugs, "kubernetes platform", undefined)).toBeNull()
  })
})

describe("parseItemList", () => {
  test("reads job cards from the category page's JSON-LD ItemList", () => {
    const html = `<script type="application/ld+json">${JSON.stringify({
      "@type": "ItemList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Data Engineer (all genders)", url: "https://jobs.instaffo.com/de/job/data-engineer-abc123abc123" },
        { "@type": "ListItem", position: 2, name: "Cloud Architect", url: "https://jobs.instaffo.com/de/job/cloud-architect-def456def456" },
      ],
    })}</script>`
    const cards = parseItemList(html)
    expect(cards).toHaveLength(2)
    expect(cards[0].id).toBe("data-engineer-abc123abc123")
    expect(cards[0].title).toBe("Data Engineer (all genders)")
    expect(cards[0].url).toBe("https://jobs.instaffo.com/de/job/data-engineer-abc123abc123")
  })

  test("strips the internal_utm_ params robots.txt disallows", () => {
    const html = `<script type="application/ld+json">${JSON.stringify({
      "@type": "ItemList",
      itemListElement: [{ "@type": "ListItem", name: "X", url: "https://jobs.instaffo.com/de/job/x-abc123abc123?internal_utm_source=category-pages" }],
    })}</script>`
    expect(parseItemList(html)[0].url).toBe("https://jobs.instaffo.com/de/job/x-abc123abc123")
  })

  test("survives a malformed JSON-LD block alongside a good one", () => {
    const html =
      `<script type="application/ld+json">{ not json </script>` +
      `<script type="application/ld+json">${JSON.stringify({
        "@type": "ItemList",
        itemListElement: [{ "@type": "ListItem", name: "Y", url: "https://jobs.instaffo.com/de/job/y-abc123abc123" }],
      })}</script>`
    expect(parseItemList(html)).toHaveLength(1)
  })
})

describe("parseJobPosting", () => {
  const build = (overrides: Record<string, unknown> = {}) =>
    `<script type="application/ld+json">${JSON.stringify({
      "@type": "JobPosting",
      title: "Senior Java-Entwickler (m/w/d)",
      datePosted: "2026-07-20",
      validThrough: "2027-08-31",
      employmentType: "FULL_TIME",
      hiringOrganization: { "@type": "Organization", name: "Treuhand Wirt­schafts­gesellschaft" },
      jobLocation: { "@type": "Place", address: { addressLocality: "Berlin", postalCode: "10178", addressCountry: "DE" } },
      description: "<h1>Rolle</h1><p>Erster Absatz.</p><p>Zweiter Absatz.</p>",
      ...overrides,
    })}</script>`

  test("maps the schema.org fields onto the result shape", () => {
    const job = parseJobPosting(build(), "java-entwickler-abc123abc123")!
    expect(job.title).toBe("Senior Java-Entwickler (m/w/d)")
    expect(job.company).toBe("Treuhand Wirtschaftsgesellschaft") // soft hyphens stripped
    expect(job.location).toBe("Berlin")
    expect(job.postalCode).toBe("10178")
    expect(job.date).toBe("2026-07-20")
    expect(job.employmentType).toBe("FULL_TIME")
    expect(job.url).toBe("https://jobs.instaffo.com/de/job/java-entwickler-abc123abc123")
  })

  test("renders the description as readable text with paragraph breaks", () => {
    const job = parseJobPosting(build(), "x-abc123abc123")!
    expect(job.description).toContain("Erster Absatz.")
    expect(job.description).not.toContain("<p>")
    expect(job.description!.split("\n").length).toBeGreaterThan(1)
  })

  test("accepts a jobLocation array", () => {
    const job = parseJobPosting(
      build({ jobLocation: [{ "@type": "Place", address: { addressLocality: "Hamburg" } }] }),
      "x-abc123abc123",
    )!
    expect(job.location).toBe("Hamburg")
  })

  test("marks a posting expired once validThrough is in the past", () => {
    expect(parseJobPosting(build({ validThrough: "2020-01-01" }), "x-abc123abc123")!.isActive).toBe(false)
    expect(parseJobPosting(build({ validThrough: undefined }), "x-abc123abc123")!.isActive).toBe(true)
  })

  test("returns null when the page carries no JobPosting", () => {
    expect(parseJobPosting(`<script type="application/ld+json">{"@type":"WebSite"}</script>`, "x")).toBeNull()
  })
})
