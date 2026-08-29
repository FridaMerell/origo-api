# Worked examples

End-to-end, copy-adaptable. Two parts:

- **Part 1** — plain API-client usage (names, observations, aggregations, vocab).
- **Part 2** — the phenology feature, built up one step at a time.

All code assumes the bundled `scripts/` modules are importable and the env vars
from [auth.md](auth.md) are set. Output shown after `# →` is **illustrative** —
real field names come from each product's OpenAPI doc.

A runnable, no-API-key demo of Part 2's logic is
[`scripts/demo_phenology.py`](../scripts/demo_phenology.py) — run it to see a
phenogram, an activity window and season statuses printed from synthetic data.

---

## Part 1 — API client basics

### 1.1 Create the client

```python
from artdatabanken_client import ArtdatabankenClient

client = ArtdatabankenClient.from_env()      # reads ARTDATABANKEN_*_KEY
```

### 1.2 Name → Dyntaxa taxon id

Everything downstream is keyed by taxon id, so this is almost always step one.

```python
client.find_taxon_ids("aurorafjäril")        # Swedish name
# → [101664]

client.find_taxon_ids("Anthocharis cardamines")   # scientific name
# → [101664]

# Inspect a hit if a name is ambiguous:
client.find_taxa("Pieris")
# → [{"taxonId": 101657, "scientificName": "Pieris", "category": {"name": "Släkte"}},
#    {"taxonId": 101660, "scientificName": "Pieris rapae", ...}, ...]
```

If a name resolves to several taxa (homonyms, or a genus + its species), show the
user the list and let them pick — don't silently take `[0]`.

### 1.3 Find the area's featureId

```python
client.areas(area_types=["Province"], search_string="Södermanland")
# → {"records": [{"featureId": "6", "areaType": "Province", "name": "Södermanland"}]}
SODERMANLAND = {"areaType": "Province", "featureId": "6"}
```

### 1.4 Count observations of a species in an area, last year

```python
flt = {
    "taxon": {"ids": [101664], "includeUnderlyingTaxa": True},
    "geographics": {"areas": [SODERMANLAND]},
    "date": {"startDate": "2024-01-01", "endDate": "2024-12-31",
             "dateFilterType": "BetweenStartDateAndEndDate"},
}
client.count_observations(flt)
# → 412
```

### 1.5 Page through the matching observations

`iter_observations` handles paging and stops at the 10 000-record cap.

```python
flt["output"] = {"fields": ["occurrence.occurrenceId", "taxon.scientificName",
                            "event.startDate", "location.municipality"]}

for obs in client.iter_observations(flt):
    print(obs["event"]["startDate"], obs["location"].get("municipality"))
# → 2024-04-28 Nyköping
#   2024-05-02 Strängnäs
#   ...
```

Need more than 10 000? Order an async export instead:

```python
job = client.order_export("DwC", flt, description="aurorafjäril SÖ 2024")
# → {"jobId": "8f1c...", "status": "Queued"}    # link emailed when ready
```

### 1.6 What species are in an area right now (taxon aggregation)

```python
recent = {
    "geographics": {"areas": [SODERMANLAND]},
    "taxon": {"ids": [4000104], "includeUnderlyingTaxa": True},   # 4000104 ≈ butterflies
    "date": {"startDate": "2025-05-01", "endDate": "2025-05-14",
             "dateFilterType": "OverlappingStartDateAndEndDate"},
}
agg = client.taxon_aggregation(recent, take=20)
# → {"records": [{"taxon": {"id": 101664, "scientificName": "Anthocharis cardamines"},
#                 "count": 37},
#                {"taxon": {"id": 101586, "scientificName": "Gonepteryx rhamni"},
#                 "count": 21}, ...]}
```

### 1.7 Resolve the "imago" activity id (do this once, cache it)

```python
vocabs = client.vocabularies()
activity = next(v for v in vocabs if v["name"] in ("Activity", "Aktivitet"))
imago_id = next(t["id"] for t in activity["values"]
                if t["value"].lower() in ("imago", "adult"))
# → 22       # then use  flt["activityIds"] = [imago_id]
```

For plants you'd pick `flowering` / `blommande` the same way. Store these ids in
a small config table; the vocabulary changes very rarely.

---

## Part 2 — Phenology feature, step by step

Goal: the user adds **aurorafjäril** (imago) for **Södermanland**. We build its
seasonal profile now; next spring the app tells them whether it's been seen yet.

### Step 1 — Create the watch record

```python
watch = SpeciesWatch.objects.create(
    taxon_id=101664,
    scientific_name="Anthocharis cardamines",
    vernacular_name="aurorafjäril",
    area_type="Province", area_feature_id="6",
    activity_id=imago_id,           # adults only, not eggs/larvae
    baseline_years=10,
)
```

### Step 2 — Pull ~10 years of history

```python
flt = {
    "taxon": {"ids": [watch.taxon_id], "includeUnderlyingTaxa": True},
    "geographics": {"areas": [{"areaType": watch.area_type,
                               "featureId": watch.area_feature_id}]},
    "date": {"startDate": "2015-01-01", "endDate": "2024-12-31",
             "dateFilterType": "BetweenStartDateAndEndDate"},
    "activityIds": [watch.activity_id],
    "output": {"fields": ["event.startDate", "taxon.id",
                          "location.decimalLatitude", "location.decimalLongitude"]},
}
records = list(client.iter_observations(flt))
# → 3 100 records
```

(If a species has > 10 000 records in the window, use `order_export("DwC", flt)`
and read the archive instead.)

### Step 3 — Build the phenogram

`decluster` first, so a single mobbed individual doesn't distort the curve
(see the "why" in [seasonality.md](seasonality.md#shared-concepts)).

```python
from phenology import phenogram, decluster, smooth, activity_window, peak_week

raw   = phenogram(decluster(records))       # {1: 0.0, ... 17: 4.0, 18: 22.0, ...}
curve = smooth(raw, window=1)               # ±1 week circular moving average
lo, hi = activity_window(curve)             # central 10–90% of records
pk     = peak_week(curve)

print(f"active weeks {lo}–{hi}, peak week {pk}")
# → active weeks 16–24, peak week 20
```

Week 20 ≈ mid-May. So: *aurorafjäril adults in Södermanland normally fly from
roughly mid-April (wk 16) to mid-June (wk 24), peaking mid-May.*

### Step 4 — Store the profile

```python
PhenologyProfile.objects.update_or_create(
    watch=watch,
    defaults=dict(
        weekly_counts={str(w): v for w, v in raw.items()},
        window_lo_week=lo, window_hi_week=hi, peak_week=pk,
        years_present=len({to_date(d).year for d in decluster(records)}),
    ),
)
```

The frontend draws the card from `weekly_counts` (52 bars, shade weeks
`lo`–`hi`, mark `peak_week`).

### Step 5 — Next year: has it been reported yet?

Nightly job. One search bounded to the current year:

```python
from phenology import iso_week, season_status
import datetime as dt

today = dt.date.today()                      # say 2025-05-06  → ISO week 19
this_year = {**flt, "date": {"startDate": "2025-01-01", "endDate": today.isoformat(),
                             "dateFilterType": "BetweenStartDateAndEndDate"}}
page = client.search_observations(this_year, take=50,
                                  sort_by="event.startDate", sort_order="Asc")

first = page["records"][0] if page["totalCount"] else None
sy = SeasonYear.objects.update_or_create(
    watch=watch, year=2025,
    defaults=dict(
        reported=bool(page["totalCount"]),
        count_ytd=page["totalCount"],
        first_seen_date=first and to_date(first["event"]["startDate"]),
        first_seen_week=first and iso_week(first["event"]["startDate"]),
        first_localities=[{"name": r["location"].get("locality"),
                           "county": r["location"].get("county")}
                          for r in page["records"][:3]],
    ),
)[0]

sy.status = season_status(
    (profile.window_lo_week, profile.window_hi_week),
    iso_week(today),
    reported_this_year=sy.reported,
    first_week_this_year=sy.first_seen_week,
)
sy.save()
```

What the statuses mean for the user:

| `status` | Shown as |
|---|---|
| `not_yet_due` | "Not expected yet — normally from week 16." |
| `due_now_unseen` | "**In season now, but no reports yet in Södermanland.** Go look." |
| `just_started` | "First seen 2025-05-03 near Nyköping — season just starting." |
| `seen` | "Reported 2025 (41 records so far)." |
| `overdue` | "Flight season nearly over and still nothing this year — unusual." |
| `season_over` | "Not recorded in 2025; season has passed." |

### Step 6 — Batch it for a whole watchlist

Many watches sharing one area → one aggregation call, then `Search` only for the
taxa that actually have records this year:

```python
ids = list(watchlist.values_list("taxon_id", flat=True))
agg = client.taxon_aggregation({
    "taxon": {"ids": ids},
    "geographics": {"areas": [SODERMANLAND]},
    "date": {"startDate": "2025-01-01", "endDate": today.isoformat(),
             "dateFilterType": "BetweenStartDateAndEndDate"},
}, take=len(ids))
seen_ids = {r["taxon"]["id"] for r in agg["records"] if r["count"]}
```

---

## Part 3 — "What should I look for in Södermanland this week?"

This reuses the per-taxon machinery across every taxon in the area, precomputed
into a `SeasonBoardEntry` table a nightly job fills. The view just reads that
table and groups rows:

```python
week = iso_week(dt.date.today())            # 19
board = SeasonBoardEntry.objects.filter(area="Province:6")

sections = {
    "on_your_list": board.filter(taxon_id__in=my_watch_ids,
                                 status__in=["due_now_unseen", "just_started"]),
    "coming_into_season": board.filter(trend="ascending",
                                       window_lo_week__gte=week - 2,
                                       window_lo_week__lte=week + 2).order_by("-score"),
    "peaking_now": board.filter(peak_week__range=(week - 1, week + 1)).order_by("-score"),
    "last_chance": board.filter(trend="descending",
                                window_hi_week__range=(week - 1, week + 2)),
    "notable_recent": board.filter(is_redlisted=True,
                                   last_report_days_ago__lte=14),
}
```

Rendered:

> **Södermanland — week 19 (early May)**
>
> *Coming into season this week*
> - **aurorafjäril** (*Anthocharis cardamines*) — normally wk 16–24, first 2025
>   record 2025-05-03 near Nyköping
> - **grönsångare** (*Phylloscopus sibilatrix*) — normally wk 18–30, not yet
>   reported here in 2025
>
> *Peaking now*
> - **vitsippa** (*Anemone nemorosa*), flowering — peak wk 18
>
> *Notable recent*
> - **bivråk** (*Pernis apivorus*), red-listed — 2 records last week

See [seasonality.md](seasonality.md) for the models, the scoring
(`in_season_score`), the counting-method choice (occupied cells vs declustered
records), and the precompute schedule.
