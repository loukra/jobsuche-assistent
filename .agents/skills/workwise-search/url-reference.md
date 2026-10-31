# Workwise.io — endpoint reference

Everything the CLI depends on, recorded so a future maintainer can repair it when
Workwise changes its API or markup. Verified live on 2026-08-31.

## Access

- `https://www.workwise.io/robots.txt` — the `User-agent: *` group contains **only
  `Allow` rules** (`/*.js$`, `/*.css$`) and no `Disallow`, so nothing is excluded for
  a generic client. Named search-engine bots (Googlebot, Bingbot, Slurp, DuckDuckBot,
  YandexBot, Google-InspectionTool) *are* disallowed from `/jobsuche/*`, `/bewerbungen/*`,
  `/jobeinladungen/*`, `/lebenslauf*`, `/einstellungen*`, `/banned*` and `/call*`.
  Neither `/jobsuche` nor `/job/…` is disallowed for `*`.
- No authentication, no API key, no cookie. A plain `fetch` with an honest User-Agent
  returns JSON from the search service and full HTML from the job pages. No bot wall,
  no JS challenge, so the CLI needs zero runtime dependencies.
- The search service is an **internal API**, not a documented public one. It is reached
  without credentials and at no cost, but it can change without notice — keep volume low.

## Why an API and not HTML

`https://www.workwise.io/jobsuche?search=<q>` returns a **client-rendered Next.js shell**:
`__NEXT_DATA__.props.pageProps.initialState` carries only UI state (`applications`,
`bookmark`, `company`, `enquiries`, `environment`, `features`, `pages`, `search`,
`serverSide`, `settings`) — **no results**. The result list arrives by XHR from the
search service. There is no server-rendered HTML to parse, so HTML scraping is not an
option for search. (Detail pages *are* server-rendered — see below.)

`https://www.workwise.io/jobs?search=<q>` is a different page: an SEO landing page of
job-category links that **ignores the `search` parameter**. Do not mistake it for search.

## The search service host

The API base is assembled client-side from the distribution domain plus a service slug.
The slugs live in the `_app` chunk (module `51370`):

```js
C.API="api", C.CANDIDATES_API="candidates", C.CHAT="chat", C.COMPANIES_API="companies",
C.EMPLOYEES_API="employees", C.IMG="img", C.JOB_PARSING="job-parsing.service",
C.MATCHING="matching", C.MULTIPOSTING="multiposting", C.NOTIFICATION="notification",
C.SEARCH="search", C.OLAF="olaf"
```

so `SEARCH` → **`https://search.workwise.io`**. A wrong host is easy to spot: the right
one answers `400 {"message":"Search Api Validation Error"}` to a bad body, while
`api.workwise.io` answers `405` to everything on these paths.

## Search — a two-step flow

### Step 1: create a search

```
POST https://search.workwise.io/v2/searches
Content-Type: application/json
```

The body is the site's **full default filter object**. A partial body is rejected with
`400 {"message":"Search Api Validation Error"}`, so every key must be present even when
unset. Defaults are lifted verbatim from the client (module `63775`, export `F`):

```json
{
  "description": "<free-text query>",
  "end": null, "hoursEnd": null, "hoursStart": null,
  "languageLevels": [],
  "leadershipExperience": "does_not_matter",
  "locationLevels": [],
  "mobileWork": null,
  "occupations": [],
  "ongoing": true,
  "remoteWork": "does_not_matter",
  "salary": null, "salaryFlexible": null, "salaryType": null,
  "searchCompanyLevels": [], "searchCompanyTagLevels": [], "searchesEnquiryTypes": [],
  "start": null,
  "workExperience": "does_not_matter",
  "worldwide": true
}
```

Response (~800 bytes): `{"data":{"search":{"id":<searchId>, …}}}`.

**The query is tokenized server-side.** `description: "Data Engineer"` comes back as
`description: ""`, `originalDescription: "Data Engineer"`, and
`occupations: [{"id":3000,"name":"Data Engineer (m/w/d)","type":"job_role"}]`. Search is
therefore semantic (occupation-matched), not literal keyword matching — result counts are
smaller and more precise than a keyword board's.

Appending `?withMatchings=true&size=<n>` returns the first page inline under
`data.matchingResult`, but the CLI uses the two-step form because only step 2 returns
`paging`.

### Step 2: page the results

```
GET https://search.workwise.io/v2/searches/<searchId>/matchings?size=<n>&page=<n>
```

| Parameter | Meaning | Notes |
|-----------|---------|-------|
| `size` | Results per page | The CLI uses 25, matching the site. 50 verified working. |
| `page` | 1-indexed page | |

Response: `{"data":{"assistedSearches":{},"matchings":[…]},"paging":{"page","pages","size","total"}}`.

### Filter parameters that work

| Filter | Field | Values | Verified |
|--------|-------|--------|----------|
| Keywords | `description` | free text | `"Data Engineer"` → 7 matches |
| Location | `locationLevels` | array of one location object (below) | `Softwareentwickler` nationwide → 109; +Berlin/30 km → 17 (see semantics note) |
| Remote | `remoteWork` | `does_not_matter` / `entirely_wanted` / `not_wanted` | 109 / 12 / 101 for `Softwareentwickler` |

The location object — note **`level` carries the radius in km**, not a hierarchy level.
Synthetic entries use a negative `id`; `lat`/`lon` are required:

```json
{"city":"Berlin","country":"Deutschland","countryCode":"DE","googlePlaceId":null,
 "id":-1,"lat":52.520008,"lon":13.404954,"level":30,
 "prefix":"","state":"Berlin","stateCode":"BE","zip":""}
```

**Trap: `city` must be non-empty, or the radius is silently discarded.** The API derives
a `limiter` from which fields are populated and echoes it back on the created search:

| Sent | Echoed `limiter` | Effect |
|------|------------------|--------|
| `city: ""` | `country_code` | **lat/lon and `level` ignored** — nationwide results (109), no error |
| `city: "Düsseldorf"` | `city` | radius applied around lat/lon (14) |

The string is never matched against the postings — Berlin's coordinates with
`city: "Düsseldorf"` return the same 17 Berlin jobs as `city: "Berlin"`, and a bare `"-"`
works too. It is purely a switch that selects the limiter. So the CLI's `"lat,lon"` form
sends the raw coordinate pair as `city`: non-empty, and self-documenting in the echo.
There is a regression test for this in `tests/search.test.ts` — a silent nationwide
fallback looks exactly like a working search.

**Semantics: a location filter matches that location OR "no fixed location".** `Softwareentwickler`
+ Berlin/30 km returns 17, of which only ~6 are Berlin-based (`jobLocationTypes:
["location"]`). The rest are `remoteWork: mandatory` postings with an empty
`locationLevels` (fully remote, no office) and `remoteWork: possible` postings based
elsewhere — Eisingen, Leipzig, Espelkamp. This is correct portal behaviour, not a broken
filter, and `tests/search.test.ts` asserts "in the city **or** has no fixed location"
rather than "every result names the city" (which passes only while on-site matches sort
first). `--remote onsite` restricts to location-tied postings (Berlin + onsite → 6, all
Berlin).

**An empty `locationLevels` means "matches any location", and is not only remote work.**
Job 125827 (`Polier Bahnbrückenbau`, a travelling Montage role) has no locationLevels and
`remoteWork: "not_possible"`, and surfaces in a Leer search. A test predicate keyed only
on `remoteWork` will flake when one of these sorts into the page — key on
`location === null` as well.

The site fills `lat`/`lon` from **Google Places**, using its own API key
(`maps.googleapis.com/maps/api/js?…&libraries=places&key=…`). There is no Workwise-side
geocoding endpoint, so the CLI ships a coordinate table for ~50 German cities in
`helpers.ts` (`CITIES`) and accepts a raw `"lat,lon"` pair for anywhere else. **Add cities
there** rather than reaching for a geocoder dependency.

### Per-result fields (`matchings[].enquiries`)

| Field | Path | Notes |
|-------|------|-------|
| id | `id` | numeric |
| title | `name` | |
| company | `company.name` | |
| location | `locationLevels[].city / .state / .country` | array; CLI joins and truncates to 3 + `+N` |
| url | built from `id` + `slug` | `https://www.workwise.io/job/<id>-<slug>` |
| employment type | `type.name` | `Festanstellung`, `Werkstudent`, `Duales Studium`, … |
| salary | `minSalary` / `maxSalary` | decimal strings, `null` when unset |
| hours | `hoursStart` / `hoursEnd` | |
| remote | `remoteWork` | `not_possible`, `possible`, … |
| new flag | `isEnquiryNew` | boolean |
| relevance | `matchings[].score` | float from the matching algorithm |

### ⚠️ No posting date, no age filter

**The search response carries no publication date**, and the filter object has no
posting-age field (`start`/`end` are the *job's* project dates, not the posting's).
`isEnquiryNew` is the only freshness signal and it is an opaque boolean.

Bulk date lookup was checked and does not exist: `api.workwise.io/v2/enquiries…` returns
`405` for every GET shape tried, and `?withEnquiryMeta=true` on the matchings endpoint
changes nothing. So `--with-dates` / `--jobage` enrich **per posting** from the detail
page (below), which is why they cost one request per result.

## Detail

```
GET https://www.workwise.io/job/<id>
```

301-redirects to the canonical `https://www.workwise.io/job/<id>-<slug>`; **the slug is
decorative**, so the CLI never needs to carry it. The page is server-rendered (~250 KB)
and carries two independent payloads:

1. **`<script type="application/ld+json">` — a schema.org `JobPosting`** in `<head>`,
   starting ~3.3 KB in, with `datePosted` at ~7.7 KB. Fields: `title`, `datePosted`,
   `validThrough`, `employmentType` (array), `description` (HTML), `workHours`, `skills`,
   `occupationalCategory`, `directApply`, `hiringOrganization{name,sameAs}`,
   `jobLocation[].address`, `baseSalary`.
   The page has **more than one `ld+json` block** (a BreadcrumbList too), so scan for
   `@type === "JobPosting"` — don't take the first one.
2. **`__NEXT_DATA__.props.pageProps.enquiry`** — richer and preferred where it overlaps:
   `firstPublished`, `lastPublished`, `description` (HTML), `shortDescription`, `status`,
   `type`, `company`, `locationLevels`, `toolLevels`, `languageLevels`, `slug`, `language`.

The CLI parses both and merges, so a change to either one leaves the other usable.

### Two traps

1. **The server ignores `Range` requests** — `Range: bytes=0-2000` returns `200` with all
   254 KB. Date enrichment instead reads the response stream and **cancels it** after
   ~32 KB (`fetchHead` in `helpers.ts`), which is enough to pass `datePosted` and keeps a
   date lookup near 10 KB instead of 250 KB.
2. **The Next.js data route does not carry the posting.**
   `/_next/data/<buildId>/_desktop/_main/job/<id>-<slug>.json` returns `200` and only
   38 KB, which looks like an attractive shortcut — but its `pageProps` holds just
   `_nextI18Next` and `initialState`, **no `enquiry`**. It also pins a `buildId` that
   changes on every deploy. Use the HTML page.
