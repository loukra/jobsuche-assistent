# Arbeitsagentur JOBBÖRSE URL Reference

The public JSON API behind **https://www.arbeitsagentur.de/jobsuche/** (Bundesagentur
für Arbeit JOBBÖRSE). These are the same calls the portal's own search page makes in a
browser; the endpoints and the API key are read from the portal's frontend config at
`https://www.arbeitsagentur.de/jobsuche/config/config.js`.

## Access

- `https://www.arbeitsagentur.de/robots.txt` is `User-agent: * / Disallow: / Allow: /` —
  the search and detail paths are permitted (checked 2026-08-31).
- **No authentication, no account, no billing.** Every request carries a fixed header:

  ```
  X-API-Key: jobboerse-jobsuche
  ```

  This is a public constant identifying the web frontend, not a personal credential, so
  the CLI ships it in `helpers.ts` rather than reading it from the environment. It is
  rotated occasionally; `ARBEITSAGENTUR_API_KEY` overrides the built-in value, and a
  `403` from the API is reported with instructions to re-read it from `config.js`.
- The API host (`rest.arbeitsagentur.de`) returns `403` with an empty body to **any**
  request missing the key — including `robots.txt` itself. Do not read that 403 as a
  block; it is a missing-header response.

## Search

```
GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs
```

| Param | Meaning | Example | CLI flag |
|-------|---------|---------|----------|
| `was` | Free-text query (title, skill, role) | `Softwareentwickler` | `--query` / `-q` |
| `wo` | Place: city, postcode, or region | `Hamburg`, `20095` | `--location` / `-l` |
| `umkreis` | Radius around `wo`, in km | `25`, `50` | `--radius` / `-r` |
| `veroeffentlichtseit` | Published within N days (max 100) | `7` | `--jobage` |
| `angebotsart` | Offer type: `1` Arbeit · `2` Selbständigkeit · `4` Ausbildung · `34` Praktikum/Trainee | `1` | `--offer-type` |
| `arbeitszeit` | `vz` Vollzeit · `tz` Teilzeit · `snw` Schicht/Nacht/WE · `ho` Heimarbeit · `mj` Minijob | `tz` | `--worktime` |
| `page` | 1-indexed page | `2` | `--page` |
| `size` | Results per page (CLI requests 50) | `50` | — (`--limit` trims client-side) |

Response shape:

```jsonc
{
  "maxErgebnisse": 137,        // total hits for the query -> meta.total
  "page": 1,
  "size": 50,
  "ergebnisliste": [ /* postings */ ],
  "woOutput": { /* resolved location */ },
  "facetten": { /* aggregations, unused */ }
}
```

Per-posting fields the CLI maps (`parseJobCards` in `cli/src/helpers.ts`):

| API field | Mapped to |
|-----------|-----------|
| `referenznummer` | `id` — e.g. `13644-311617-S` |
| `stellenangebotsTitel` (fallback `hauptberuf`) | `title` |
| `firma` | `company` |
| `stellenlokationen[0].adresse.plz` + `.ort` | `location` (`+N` suffix when several) |
| `stellenlokationen[0].adresse.region` | `region` (title-cased from `NIEDERSACHSEN`) |
| `veroeffentlichungszeitraum.von` → `datumErsteVeroeffentlichung` → `aenderungsdatum` | `date` |
| `hauptberuf` | `profession` |
| `stellenangebotsart` | `offerType` (`ARBEIT` → `Arbeit`) |
| `homeofficemoeglich` | `homeoffice` |
| `arbeitszeitVollzeit` | `fulltime` |
| `vertragsdauer` | `contractDuration` |
| `eintrittszeitraum.von` | `entryDate` |
| `entfernung` | `distanceKm` |
| `externeURL` (note the capitalised `URL`) | `externalUrl` |

The public posting page is `https://www.arbeitsagentur.de/jobsuche/jobdetail/<referenznummer>`.

## Detail

```
GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/<base64url(referenznummer)>
```

The path segment is the **base64url encoding of the reference number**, not the raw
value — a raw refnr returns `404`. `10000-1183204759-S` → `MTAwMDAtMTE4MzIwNDc1OS1T`.

Adds to the search fields: `stellenangebotsBeschreibung` (the body), `gehaltsspanneVon`
/ `gehaltsspanneBis` / `artDerVerguetung` (salary), `istArbeitnehmerUeberlassung`,
`istPrivateArbeitsvermittlung`, `quereinstiegGeeignet`, `istBetreut`.

## Quirks found during investigation (2026-08-31)

- **`v4` and `v2` of the search endpoint are retired** — they return `403` even with a
  valid key. Only `pc/v6/jobs` works. The *detail* endpoint is still `pc/v4/jobdetails`.
- **Descriptions are Markdown, not plain text.** They arrive with `##` headings, `-`
  bullets, real newlines, and CommonMark backslash escapes (`C\#`). `cleanDescription`
  unescapes exactly the CommonMark punctuation set and leaves other backslashes alone.
- **`&` is stripped from company names upstream.** `Stellenwert GmbH & Co. KG` is served
  by the API as `Stellenwert GmbH   Co. KG`. This is the portal's data, not a parsing
  bug — do not "fix" it in the client.
- **`KEINE_ANGABE` / `KEINE_ANGABEN` is the API's "unknown" sentinel**, used instead of
  omitting a field. The CLI maps it to `null` so it never surfaces as a value.
- **A posting's detail record can list more locations, in a different order, than the
  search hit shows.** The search hit reflects the location that matched `wo`; detail
  lists all of them. Both render the first entry plus a `(+N)` count.
- **Withdrawn or expired postings return `404` from the detail endpoint.** There is no
  status field in the API, so `isActive: true` means only "the portal still serves it".
- An empty query returns the entire database, so the CLI requires `--query` or
  `--location`.
