import { describe, expect, test } from "bun:test"
import {
  cleanDescription,
  encodeRefnr,
  formatRegion,
  jobUrl,
  jobageToVeroeffentlichtseit,
  offerTypeCode,
  parseJobCards,
  parseTotal,
  workTimeCode,
} from "../src/helpers"
import { normalizeId } from "../src/commands/detail"
import { buildUrl } from "../src/commands/search"

const SAMPLE = {
  maxErgebnisse: 15,
  ergebnisliste: [
    {
      referenznummer: "13644-311617-S",
      stellenangebotsTitel: "Softwareentwicklerin / Softwareentwickler (m/w/d)",
      firma: "IT.Niedersachsen",
      stellenangebotsart: "ARBEIT",
      hauptberuf: "Softwareentwickler/in",
      arbeitszeitVollzeit: true,
      vertragsdauer: "UNBEFRISTET",
      verguetungsangabe: "KEINE_ANGABEN",
      homeofficemoeglich: true,
      eintrittszeitraum: { von: "2026-09-01" },
      veroeffentlichungszeitraum: { von: "2026-08-20" },
      datumErsteVeroeffentlichung: "2026-08-19",
      entfernung: 3,
      stellenlokationen: [
        { adresse: { plz: "20095", ort: "Hamburg", region: "NIEDERSACHSEN", land: "DEUTSCHLAND" } },
        { adresse: { plz: "30159", ort: "Hannover", region: "NIEDERSACHSEN" } },
      ],
    },
    // A malformed record: no refnr. Must be skipped, not break the page.
    { stellenangebotsTitel: "Kaputt" },
    // Minimal record: every optional field absent.
    { referenznummer: "1-2-S", stellenangebotsTitel: "Minimal" },
    // The API's "unknown" sentinel must not surface as data.
    { referenznummer: "3-4-S", stellenangebotsTitel: "Sentinel", vertragsdauer: "KEINE_ANGABE" },
  ],
}

describe("parseJobCards", () => {
  test("maps the documented fields", () => {
    const cards = parseJobCards(SAMPLE)
    expect(cards).toHaveLength(3)
    const [job] = cards
    expect(job.id).toBe("13644-311617-S")
    expect(job.company).toBe("IT.Niedersachsen")
    expect(job.location).toBe("20095 Hamburg (+1)")
    expect(job.region).toBe("Niedersachsen")
    expect(job.date).toBe("2026-08-20")
    expect(job.offerType).toBe("Arbeit")
    expect(job.homeoffice).toBe(true)
    expect(job.distanceKm).toBe(3)
    expect(job.contractDuration).toBe("Unbefristet")
    expect(job.url).toBe("https://www.arbeitsagentur.de/jobsuche/jobdetail/13644-311617-S")
  })

  test("missing values are null, never omitted", () => {
    const minimal = parseJobCards(SAMPLE)[1]
    for (const key of ["company", "location", "date", "region", "homeoffice", "externalUrl", "distanceKm", "contractDuration"] as const) {
      expect(minimal).toHaveProperty(key)
      expect(minimal[key]).toBeNull()
    }
  })

  test("the KEINE_ANGABE sentinel becomes null, not a visible enum", () => {
    expect(parseJobCards(SAMPLE)[2].contractDuration).toBeNull()
  })

  test("a non-list payload yields no results rather than throwing", () => {
    expect(parseJobCards(null)).toEqual([])
    expect(parseJobCards({ ergebnisliste: "nope" })).toEqual([])
  })

  test("parseTotal reads maxErgebnisse", () => {
    expect(parseTotal(SAMPLE)).toBe(15)
    expect(parseTotal({})).toBeNull()
  })
})

describe("cleanDescription", () => {
  test("decodes entities, strips tags, keeps paragraph breaks", () => {
    const raw = "Erste Zeile<br>Zweite Zeile</p><p>Neuer Absatz &amp; mehr &#228;h"
    expect(cleanDescription(raw)).toBe("Erste Zeile\nZweite Zeile\n\nNeuer Absatz & mehr äh")
  })

  test("unescapes Markdown punctuation escapes, leaves other backslashes", () => {
    expect(cleanDescription("Kenntnisse in C\\# und R&D \\& mehr")).toBe("Kenntnisse in C# und R&D & mehr")
    expect(cleanDescription("Pfad C:\\Users\\dev")).toBe("Pfad C:\\Users\\dev")
  })

  test("empty input is null", () => {
    expect(cleanDescription("   ")).toBeNull()
    expect(cleanDescription(undefined)).toBeNull()
  })
})

describe("id handling", () => {
  test("base64url round-trips the reference number", () => {
    expect(encodeRefnr("10000-1183204759-S")).toBe("MTAwMDAtMTE4MzIwNDc1OS1T")
  })

  test("normalizeId accepts refnr, URL, and base64url", () => {
    expect(normalizeId("13644-311617-S")).toBe("13644-311617-S")
    expect(normalizeId("https://www.arbeitsagentur.de/jobsuche/jobdetail/13644-311617-S")).toBe("13644-311617-S")
    expect(normalizeId("MTAwMDAtMTE4MzIwNDc1OS1T")).toBe("10000-1183204759-S")
    expect(normalizeId("")).toBeNull()
  })

  test("jobUrl percent-encodes the reference number", () => {
    expect(jobUrl("12265-485869_JB5229683-S")).toContain("12265-485869_JB5229683-S")
  })
})

describe("parameter mapping", () => {
  test("jobage rounds up to the next honoured bucket and has no filter beyond 28 days", () => {
    expect(jobageToVeroeffentlichtseit(1)).toBe("1")
    expect(jobageToVeroeffentlichtseit(2)).toBe("7")
    expect(jobageToVeroeffentlichtseit(7)).toBe("7")
    expect(jobageToVeroeffentlichtseit(15)).toBe("28")
    expect(jobageToVeroeffentlichtseit(29)).toBeNull()
    expect(jobageToVeroeffentlichtseit(365)).toBeNull()
    expect(jobageToVeroeffentlichtseit(9999)).toBeNull()
    expect(jobageToVeroeffentlichtseit(0)).toBeNull()
  })

  test("offer type and worktime map to portal codes", () => {
    expect(offerTypeCode("ausbildung")).toBe("4")
    expect(offerTypeCode("arbeit")).toBe("1")
    expect(offerTypeCode("unbekannt")).toBeNull()
    expect(workTimeCode("teilzeit")).toBe("tz")
    expect(workTimeCode("homeoffice")).toBe("ho")
    expect(workTimeCode(undefined)).toBeNull()
  })

  test("formatRegion title-cases the enum", () => {
    expect(formatRegion("NORDRHEIN_WESTFALEN")).toBe("Nordrhein Westfalen")
    expect(formatRegion(null)).toBeNull()
  })

  test("buildUrl emits the portal's parameter names", () => {
    const url = new URL(
      buildUrl({ query: "Data Engineer", location: "Berlin", radius: 25, jobage: 7, offerType: "arbeit", worktime: "vollzeit", page: 2, format: "json" }),
    )
    expect(url.searchParams.get("was")).toBe("Data Engineer")
    expect(url.searchParams.get("wo")).toBe("Berlin")
    expect(url.searchParams.get("umkreis")).toBe("25")
    expect(url.searchParams.get("veroeffentlichtseit")).toBe("7")
    expect(url.searchParams.get("angebotsart")).toBe("1")
    expect(url.searchParams.get("arbeitszeit")).toBe("vz")
    expect(url.searchParams.get("page")).toBe("2")
  })

  test("an unset jobage sends no freshness filter", () => {
    const url = new URL(buildUrl({ query: "test", jobage: 9999, page: 1, format: "json" }))
    expect(url.searchParams.get("veroeffentlichtseit")).toBeNull()
  })
})
