# StepStone.de — endpoint reference

Everything the CLI depends on, recorded so a future maintainer can repair the parsers
when StepStone changes its markup. Verified live on 2026-08-31.

## Access

- `https://www.stepstone.de/robots.txt` — `User-agent: *` is broadly permissive.
  Relevant `Disallow` rules cover legacy `/5/…` endpoints, `/m/`, `/mobile/`,
  `/public-api/`, `/jobagent/`, `/listingprint/`, and `/?*` (query strings on the
  bare root). **Neither `/jobs` nor `/stellenangebote--…` is disallowed.**
- No authentication, no API key, no cookie. A plain `fetch` with an honest
  User-Agent returns fully server-rendered HTML — there is no JS challenge and no
  bot wall, so the CLI needs zero runtime dependencies.

## Search

```
GET https://www.stepstone.de/jobs?q=<keywords>&where=<Ort>&radius=<km>&ag=age_<days>&wfh=<1|2>&page=<n>
```

| Parameter | Meaning | Notes |
|-----------|---------|-------|
| `q`      | Keywords (title, skill, company) | URL-encoded. Omit for a location-only search. |
| `where`  | City or region | German place name, e.g. `Berlin`, `München`, `Nordrhein-Westfalen`. |
| `radius` | Radius in km around `where` | Portal default is 30. |
| `ag`     | Posting age, as `age_<days>` | The UI exposes only `age_1` / `age_7`, but arbitrary day counts work. Verified totals for `q=data engineer&where=Berlin&radius=30`: none→235, `age_1`→12, `age_3`→42, `age_7`→119, `age_14`→199, `age_30`→235. |
| `wfh`    | Home-office facet | `1` = teilweise Home-Office (hybrid), `2` = nur Home-Office (remote). |
| `page`   | 1-indexed page | 25 results per page. Omitted for page 1. |

There is also an SEO path form (`/jobs/<slug>/in-<ort>`) that the site links
internally. The CLI uses the query-parameter form because it accepts arbitrary
keywords without slugification.

### Response structure

Server-rendered HTML. **CSS class names are build-hashed** (`res-xaz43y`,
`res-kyg8or`, `res-9lmmub`) and change on every deploy — never anchor on them.
Anchor on the `data-at` attributes, which have been stable:

| Field | Anchor |
|-------|--------|
| Card boundary | `<article … id="job-item-<id>" data-at="job-item">` — the numeric id is in the `id` attribute |
| Title + detail URL | `<a href="…" data-at="job-item-title">` (href may be site-relative) |
| Company | `data-at="job-item-company-name"` |
| Location | `data-at="job-item-location"` |
| Posting age | `data-at="job-item-timeago"` — relative German text ("vor 6 Tagen", "Heute", "Gestern") |
| Home office | `data-at="job-item-work-from-home"` |
| Total matches | inline analytics JSON: `searchResultsTotalJobCount":<n>` |

Two parsing traps, both covered by tests:

1. **Inline `<style>` blocks live inside the cards.** StepStone emits an emotion
   `<style data-emotion="…">` element inside the first card that uses each generated
   class. Stripping only tags leaves the CSS rules behind as "text" — the first
   result's title comes out as `.res-xrpel9{box-sizing:border-box…`. `<style>` and
   `<script>` blocks must be removed wholesale before text extraction.
2. **The company and location fields wrap a nested icon `<span>`** (a `<svg>` inside
   an `ICON_CONTAINER` span) before the text. A non-nesting regex stops at the first
   `</span>` and returns an empty string, so extraction must track tag depth.

The total-count payload is HTML-escaped inline JSON whose quote escaping varies
between responses (`&quot;` in some, `&#34;` in others), so the regex must tolerate
both — and must not match the `34` inside `&#34;`.

`window.__PRELOADED_STATE__` exists on the page but carries only `header`, `modal`,
`searchBar`, and `footer` — **not** the job results. There is no usable JSON payload
for the result list; HTML parsing is required.

## Detail

```
GET https://www.stepstone.de/stellenangebote--<slug>--<id>-inline.html
```

**The `<slug>` is decorative.** The server resolves the posting from the numeric id
alone, so the CLI sends the placeholder `x`:
`https://www.stepstone.de/stellenangebote--x--<id>-inline.html` returns byte-identical
content to the full-slug URL.

`https://www.stepstone.de/offers/<id>` returns 403 — do not use it.

### Response structure

The page embeds a **schema.org `JobPosting` as JSON-LD**, which is far more stable
than the rendered markup and is the CLI's only detail source:

```html
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting", …}</script>
```

| Field | JSON-LD path |
|-------|--------------|
| Title | `.title` |
| Canonical URL | `.url` |
| Posted date | `.datePosted` (ISO timestamp — the true date, unlike the search page's relative text) |
| Deadline | `.validThrough` |
| Employment type | `.employmentType` (e.g. `FULL_TIME`) |
| Industry | `.industry` |
| Company | `.hiringOrganization.name`, `.hiringOrganization.url` |
| Location | `.jobLocation.address.addressLocality` (+ `.addressRegion`, often empty) |
| Description | `.description` — an **HTML fragment**, needs entity decoding and tag stripping |

The parser also accepts a `JobPosting` nested inside an `@graph` array, and skips an
unparseable `ld+json` block rather than giving up, since the page carries more than one.

## Rate limiting

No documented limit. The CLI retries 429/5xx with exponential backoff plus jitter
(max 6 attempts, capped at 8 s) and a 20 s request timeout. No throttling was hit
during development at a few dozen requests.
