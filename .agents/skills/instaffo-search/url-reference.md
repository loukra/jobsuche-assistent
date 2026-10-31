# Instaffo URL Reference

Endpoint and parsing notes for `jobs.instaffo.com`, recorded 2026-08-31. This is the
file to update when the portal changes its markup.

## robots.txt (jobs.instaffo.com)

```
User-agent: *
Disallow: /api/
Disallow: /admin/
Disallow: /auth/
Disallow: /apply
Disallow: /internal-error
Disallow: /*internal_utm_
Disallow: /*?q=

Sitemap: https://jobs.instaffo.com/sitemap.xml
```

What this means for the CLI:

- **`/api/` is disallowed** — and that is exactly where the site's own free-text search
  runs. Hence no search endpoint is used.
- **`/*internal_utm_` is disallowed** — job-card anchors on category pages carry
  `?internal_utm_source=category-pages&...`. The CLI uses the clean canonical URLs from
  the JSON-LD `ItemList` instead of those hrefs.
- `/*?q=` is disallowed, but `q` is only Next.js's **image-quality** parameter
  (`/_next/image?url=...&q=75`). It is not a search parameter — do not be misled by it.
- `?page=` and `?search=` are **not** disallowed.

## The search problem

`GET /de/jobs?search=data+engineer` returns HTTP 200 with a body byte-near-identical to
the unfiltered `/de/jobs` (199,492 vs 199,409 bytes) and **zero** `/de/job/` links. The
`?search=` parameter is advertised in the page's schema.org `SearchAction`
(`urlTemplate: https://jobs.instaffo.com/de/jobs?search={search_term_string}`) but is
handled client-side only. There is no server-rendered keyword search.

## Endpoints actually used

| Purpose | URL | Notes |
|---|---|---|
| Category index | `GET /sitemap-category-pages.xml` | ~499 German category slugs. Cached 1h. |
| Job index | `GET /sitemap-jobs.xml` | ~1,947 German postings, each with `<lastmod>`. ~2.5 MB. Cached 1h. |
| Category page | `GET /de/jobs/<slug>?page=<n>` | 10 jobs/page. `page` is real server-side pagination. |
| Detail page | `GET /de/job/<slug>` | Full schema.org `JobPosting` JSON-LD. |

### Category slug grammar

`<role>` or `<role>-<city>`, e.g. `backend-entwickler`, `backend-entwickler-berlin`,
`data-jobs`, `account-management-remote`. A few are bare cities (`berlin`, `bonn-jobs`).

Cities use German transliteration, **not** accent-stripping:
`muenchen`, `duesseldorf`, `koeln`, `nuernberg` (never `munchen`/`dusseldorf`).
`slugify()` in `helpers.ts` implements this.

Category-page counts by city (a proxy for coverage): muenchen 220, berlin 185,
remote 180, hamburg 160, frankfurt 160, koeln 150, stuttgart 145, duesseldorf 140,
essen 85, nuernberg 80, leipzig 70, mannheim 65, dresden 60, hannover 55, dortmund 50.
**No page exists for smaller cities** (Flensburg, Husum, …).

### Pagination check

- `?page=2` → different first `ItemList` item. **Works.**
- `?seite=2` → identical to page 1. Ignored.
- `/de/jobs/data-jobs/2` → 404.

## Parsing anchors

### Category page → job list

Parse the **JSON-LD `ItemList`**, not the DOM:

```json
{"@type":"ItemList","itemListElement":[
  {"@type":"ListItem","position":1,
   "name":"Data Analyst/Softwareentwickler (m/w) Data Warehouse",
   "url":"https://jobs.instaffo.com/de/job/data-analyst-softwareentwickler-m-w-data-warehouse-7118c289c95d"}
]}
```

The rendered anchors carry the same links but their class names are build-hashed
(`index-module-scss-module__oO5Yqa__root index-module-scss-module__oO5Yqa__default`) and
change on every deploy, and their hrefs carry the disallowed `internal_utm_*` params.
The `ItemList` gives clean canonical URLs and the real, current job titles.

`ItemList` yields **id/title/url only** — no company, location or date. Those come from
hydrating the detail page.

### Detail page → posting

Parse the JSON-LD object with `"@type":"JobPosting"`:

| Field | Path | Example |
|---|---|---|
| title | `title` | `(Senior) Java-Entwickler (m/w/d)` |
| company | `hiringOrganization.name` | `ID GmbH & Co. KGaA` |
| posted | `datePosted` | `2026-07-20` |
| expires | `validThrough` | `2027-08-31` |
| employment | `employmentType` | `FULL_TIME` (may be an array) |
| city | `jobLocation.address.addressLocality` | `Berlin` |
| postcode | `jobLocation.address.postalCode` | `10178` |
| country | `jobLocation.address.addressCountry` | `DE` |
| description | `description` | HTML string: `<h1>`, `<p>`, `<br>` (no `<li>`) |

`jobLocation` may be an object or an array — handle both.

## Job id format

Slug + trailing 12-hex: `finanzbuchhalter-m-w-d-740946f4ab7d`. The hex alone identifies
the posting but the **full slug is required to build the detail URL**, so `id` in the
CLI output is the whole slug. `detail` accepts a bare hex and resolves it through the
job sitemap.

## Data quirks

- **Run-together words in descriptions.** Instaffo flattens bullet lists into a `<p>`
  with no separator, e.g. `…Anlagevermögen und ZahlungsverkehrDurchführung der
  Debitoren- und KreditorenbuchhaltungErstellung von Jahresabschluss…`. This is in the
  portal's source data. Not repaired by the CLI — word boundaries cannot be recovered
  reliably.
- **Soft hyphens (U+00AD)** appear inside company names
  (`Wirt<AD>schafts<AD>prüfungs<AD>gesellschaft`). Stripped by `stripInvisibles()`,
  along with zero-width characters.
- **Stale `datePosted`.** Live postings carry dates years in the past (2020, 2024) with
  a future `validThrough`. Age filtering on `datePosted` is therefore aggressive.
- **Slug/title drift.** `java-softwareentwickler-full-stack-m-w-d-08d2c6930c58` is now
  titled "Softwareentwickler – Schwerpunkt Angular". Trust the JSON-LD `title`.
- **Cross-city results on city category pages.** `backend-entwickler-berlin` returned a
  München posting. The portal's curation, not a parsing error.
