# Seasonality: species watchlist + geographic "what to look for"

Two features, one engine. The engine turns observation history into a
**phenogram** (week-of-year activity curve) and reads the current year against
it. Pure logic lives in [`scripts/phenology.py`](../scripts/phenology.py) (no
deps); the API calls and Django models wrap around it.

> For a step-by-step walkthrough with real code and sample output, read
> [examples.md](examples.md) first, or run `python scripts/demo_phenology.py`.

## How the pieces fit

```
                 SOS API (history, ~10 yrs, per taxon+area+activity)
                        │
       decluster() ─────┤   collapse twitcher pile-ons
                        ▼
        phenogram()  →  smooth()  →  {week: value}      ── the seasonal curve
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
 activity_window()   peak_week()      limb(week)         ── read the curve
   (wk_lo, wk_hi)                   ascending/descending
        │
        ▼
  stored PhenologyProfile  (per SpeciesWatch, rebuilt yearly)

           ... then each year, cheaply ...

 SOS API (this year only)  →  first record? count?      ── one Search / Aggregation call
        │
        ▼
 season_status(window, this_week, reported?, first_week)
        │
        ▼
  stored SeasonYear.status   →   UI: "in season now, not seen yet"
```

**Feature 1** = one `SpeciesWatch` → its `PhenologyProfile` + a yearly
`SeasonYear` status.
**Feature 2** = the same, run over every taxon in an area, ranked by
`in_season_score()` into a `SeasonBoardEntry` table the UI groups into sections.

Function reference: every name above is in
[`scripts/phenology.py`](../scripts/phenology.py); API calls are on
`ArtdatabankenClient` in [`scripts/artdatabanken_client.py`](../scripts/artdatabanken_client.py).

## Shared concepts

- **Phenogram** — `{iso_week: value}` for weeks 1..52. Built from N years of
  records, then `smooth()`ed and `normalize()`d to "fraction of annual records
  in week *w*".
- **Activity window** — `activity_window(hist)` → `(week_lo, week_hi)`, the weeks
  holding the central 10–90% of records. This is the "should be active roughly
  weeks 20–34" statement.
- **Activity term** — for insects you almost always want the **imago** (adult)
  stage, not larvae/eggs; for plants, **flowering**. In Artportalen this is the
  *Aktivitet* field. In SOS it's a vocabulary-backed filter — find the id:
  `GET /Vocabularies`, locate the `Activity` vocabulary (and/or `LifeStage`),
  read the term id for `imago` / `flowering` / `blommande`. Filter key in the
  search body is `activityIds: [<id>]` (verify the exact name against the SOS
  OpenAPI doc — some versions use `lifeStageIds`). Store the resolved id per
  watchlist entry with a sensible default by taxon group.
- **Effort correction** — observer effort swings ~10× across the year. When it
  matters (cross-taxon ranking), also pull a phenogram of *all* observations in
  the area and `divide()` the taxon curve by it.
- **Counting method** — *reports ≠ individuals ≠ presence.* One staked rarity
  gets mobbed by hundreds of reporters, so raw report counts measure twitcher
  interest, not the species. There is a per-record quantity
  (`occurrence.organismQuantity` + `organismQuantityType`; also
  `individualCount`) but it is often blank and the unit varies (individuals,
  pairs/territories for birds, tussocks/m² for plants), and the aggregation
  endpoints don't sum it. Preference order for the phenogram value:
  1. **Occupied grid cells per week** — `GeoGridAggregation` per week window,
     count cells with presence. A one-spot rarity = 1 cell however many people
     file. Twitcher-proof, unit-free. **Default for phenograms + board ranking.**
  2. **Declustered records** — `phenology.decluster()` collapses same-place
     same-taxon reports to one per week; keeps a long-staying individual's
     duration, kills the same-week pile-on.
  3. **Raw report count** — only as a secondary "buzz" signal.
  4. **Summed `organismQuantity`** (one `organismQuantityType`) — only as a
     rough "strong year / weak year" abundance hint for common species; pass it
     as `phenogram(dates, weights=...)`.
  A mobbed rarity *is* what you want in the geographic summary's **Notable
  recent** section — the bias only hurts the normal phenology curve of common
  species, which it rarely touches.

## Feature 1 — Add a species, get its phenology card, track it each year

### Django model sketch

```python
class SpeciesWatch(models.Model):
    taxon_id       = models.IntegerField()           # Dyntaxa id
    scientific_name= models.CharField(max_length=200)
    vernacular_name= models.CharField(max_length=200, blank=True)
    area_type      = models.CharField(max_length=32)  # "Province" | "County" | "Custom"
    area_feature_id= models.CharField(max_length=64)
    activity_id    = models.IntegerField(null=True)   # imago / flowering / null=any
    baseline_years = models.IntegerField(default=10)

class PhenologyProfile(models.Model):      # one per SpeciesWatch, rebuilt yearly
    watch          = models.OneToOneField(SpeciesWatch, on_delete=models.CASCADE)
    weekly_counts  = models.JSONField()    # {"1": 0, ... "52": 3.2}  (raw)
    window_lo_week = models.IntegerField()
    window_hi_week = models.IntegerField()
    peak_week      = models.IntegerField()
    years_present  = models.IntegerField()
    computed_at    = models.DateTimeField(auto_now=True)

class SeasonYear(models.Model):            # one per watch per calendar year
    watch              = models.ForeignKey(SpeciesWatch, on_delete=models.CASCADE)
    year               = models.IntegerField()
    reported           = models.BooleanField(default=False)
    first_seen_date    = models.DateField(null=True)
    first_seen_week    = models.IntegerField(null=True)
    count_ytd          = models.IntegerField(default=0)
    first_localities   = models.JSONField(default=list)   # [{name, county}]
    status             = models.CharField(max_length=24)  # from phenology.season_status
    checked_at         = models.DateTimeField(auto_now=True)
```

### Building the profile (once, then refresh yearly)

Pull the history, build the curve:

```python
from phenology import phenogram, decluster, smooth, activity_window, peak_week

flt = {
    "taxon": {"ids": [watch.taxon_id], "includeUnderlyingTaxa": True},
    "geographics": {"areas": [{"areaType": watch.area_type, "featureId": watch.area_feature_id}]},
    "date": {"startDate": f"{y0}-01-01", "endDate": f"{y1}-12-31",
             "dateFilterType": "BetweenStartDateAndEndDate"},
    "output": {"fields": ["event.startDate", "taxon.id",
                          "location.decimalLatitude", "location.decimalLongitude"]},
}
if watch.activity_id:
    flt["activityIds"] = [watch.activity_id]

records = list(client.iter_observations(flt))
hist    = smooth(phenogram(decluster(records)), 1)   # twitcher-resistant
lo, hi  = activity_window(hist)
```

For the season board's cross-taxon ranking, build `hist` from per-week
`GeoGridAggregation` cell counts instead (see "Counting method" above).

For an area with lots of history the 10 000-record search cap bites — use
`client.order_export("DwC", flt)` (async, emailed) and build the histogram from
the archive, or aggregate year-by-year. Birds/common taxa: prefer the export.

Fallback / cross-check for well-photographed taxa: **iNaturalist**
`GET /observations/histogram?taxon_id=&place_id=&interval=week_of_year&date_field=observed`
returns the curve directly.

### The card

- Phenogram chart: 52-week bars, activity window shaded, peak marked. Frontend
  chart from `weekly_counts`.
- "Typically active **weeks 20–34** (mid-May to late Aug), peak **week 26**."
- Distribution mini-map (optional): `POST /Observations/GeoGridAggregation` with
  the same filter, no date restriction → hex counts.
- This year's status (see below).

### The yearly check ("has it been reported yet?")

Nightly job, per watch, cheap — one search bounded to this year:

```python
this_year = {**flt, "date": {"startDate": f"{Y}-01-01", "endDate": today.isoformat(),
                             "dateFilterType": "BetweenStartDateAndEndDate"}}
page = client.search_observations(this_year, take=50, sort_by="event.startDate", sort_order="Asc")
```

Fill `SeasonYear` from the first record + `totalCount`, then:

```python
from phenology import iso_week, season_status
status = season_status(
    (profile.window_lo_week, profile.window_hi_week),
    iso_week(today),
    reported_this_year=bool(page["totalCount"]),
    first_week_this_year=iso_week(sy.first_seen_date) if sy.first_seen_date else None,
)
```

Statuses: `not_yet_due` · `due_now_unseen` · `just_started` · `seen` ·
`overdue` (window passed, still nothing — interesting!) · `season_over`.

Batch tip: for many watches sharing one area, send one
`POST /Observations/TaxonAggregation` with `taxon.ids = [all watched ids]` and
`date` = this year → per-taxon `count`, then only hit `Search` for the taxa that
have records (to get first date + locality).

## Feature 2 — Geographic nature summary ("I'm in Södermanland, what should I look for?")

### Area

"Södermanland" is both a province (*landskap*) and a county (*Södermanlands
län*). Resolve with `GET /Areas?areaTypes=Province&searchString=Södermanland`
(use `Province` for the nature-flavoured area, `County` to match administrative
datasets) → `featureId`. Let the user pick either; also support a point +
`maxDistanceFromPoint` for "near me".

### Season board build (nightly, per configured area)

1. **Baseline**, per taxon: phenogram from ~10y history in the area + activity
   window + peak. Same as Feature 1 but for the whole area's taxon list. Do this
   from a yearly DwC export, not thousands of searches. Restrict to taxon groups
   you care about (birds, butterflies, dragonflies, vascular plants, macrofungi)
   via `taxon.ids` of the group's parent + `includeUnderlyingTaxa`.
2. **Effort curve**: phenogram of *all* observations in the area → `divide()`.
3. **Current year**: one `TaxonAggregation` for [Jan 1, today] and one for
   [today−14d, today].
4. **Score** every taxon with `in_season_score(baseline, current_week,
   first_week_this_year=…, reported_this_year=…, weeks_of_data=years_present)`.
5. Materialise a `SeasonBoardEntry(area, taxon_id, score, window, peak,
   first_seen_this_year, trend)` table the view reads.

### What the summary shows

| Section | Rule |
|---|---|
| **Due now on your list** | `SpeciesWatch` for this area ∩ `status in {due_now_unseen, just_started}` — highest priority |
| **Coming into season this week** | `limb == "ascending"` and `current_week` within ~2 weeks of `window_lo`, ranked by score |
| **Peaking now** | `current_week` near `peak_week`, high raw counts — good for casual users |
| **Last chance** | `limb == "descending"`, near `window_hi` |
| **Notable recent** | red-listed (`taxon.redListCategories`) or low-baseline taxa reported in the area in the last 14 days → "unusual sighting", shown separately from "in season" |

Each row: sv + scientific name, typical window, this year's first record (date +
approximate locality), count last 2 weeks, link to the Artportalen filtered view.

## Precompute schedule

| Job | Cadence | Cost |
|---|---|---|
| Baseline phenograms (per area / per watch) | yearly, + incremental current-year refresh weekly | DwC exports, a handful of calls |
| Current-year aggregations | nightly | 2 `TaxonAggregation` calls per area |
| Watchlist `SeasonYear` status | nightly | 1 batched aggregation + a few searches per area |
| Vocabulary ids (activity/lifeStage) | on deploy / monthly | 1 call |

Everything the UI renders comes from materialised tables, so page loads never
wait on api.artdatabanken.se and usage stays well inside the rate limits.

## Supplementary APIs for this feature

- **iNaturalist** `api.inaturalist.org/v1` — `/observations/histogram` (turnkey
  seasonal curve), `/observations/species_counts?place_id=&d1=&d2=` ("what's
  being seen now here"). No key.
- **GBIF** `api.gbif.org/v1` — `/occurrence/search` with `facet=month`, cheap
  deep baselines without spending SOS quota; blends cross-border datasets. No key.
- **SMHI Open Data** `opendata-download-metobs.smhi.se` — air temperature →
  growing-degree-days; shifts "normally due now" to "likely this week given the
  spring has been warm/cold". No key.
- **Naturens kalender / Svenska fenologinätverket** (SLU) — real phenological
  events (leafing, flowering, first frog, bird arrival); likely a GBIF dataset.
  Ground truth rather than inference from counts.
