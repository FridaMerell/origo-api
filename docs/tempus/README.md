# Tempus documentation

The position-based interesting spots endpoint is documented in
[`routes.md`](routes.md).

Tempus handles species taxonomy, seasonality, observations, checklists, nature
routes, and short-lived BirdNET detections.

## Feature documentation

- [BirdNET](birdnet/README.md)
  - [API contract](birdnet/api.md)
  - [Fake detection data](birdnet/fake-data.md)
- [Phenograms](phenograms.md)
- [Routes and suggested stops](routes.md)
- [Observations and checklists](observations-and-checklists.md)
- [Registering an observation with a user token](extern-klient-observationer.md)
- [Species and taxonomy](species-and-taxonomy.md)
- [Geography and GeoJSON](geography.md)
- [Locales](observations-and-checklists.md#locales)
- [Lantmäteriet: marktäcke och administrativa gränser](lantmateriet-marktacke.md)
  - [Frontend handoff: Tempus kartgenerator](marktacke-frontend-handoff.md)
  - [Background land-cover/hydrography/place-name/building prefetch](land-cover-fetch-handoff.md)
- [Lantmäteriet: Ortnamn Direkt (place names)](lantmateriet-ortnamn.md)
- [OpenStreetMap: buildings (Overpass)](openstreetmap-buildings.md)
- [Lantmäteriet: Byggnad Direkt (buildings) — not in use](lantmateriet-byggnad.md)
- [Trafikverket: roads (NVDB)](trafikverket-roads.md)
- [Adding a new Locale data source](adding-a-locale-data-source.md)
- [Background tasks](background-tasks.md)
- [Permissions](permissions.md)
- [API index](api.md)
- [Operations and configuration](operations.md)
- [Artdatabanken and Artportalen](artdatabanken/README.md)
  - [API products](artdatabanken/apis.md)
  - [Authentication](artdatabanken/authentication.md)
  - [SOS observations and phenograms](artdatabanken/observations-and-phenograms.md)
  - [Future Artportalen reporting](artdatabanken/artportalen-write.md)

## Main API prefix

Most Tempus resources are exposed beneath `/api/tempus/` through Django REST
Framework. Authentication and object scoping vary by resource and are described
on each feature page.

## Position-based interesting spots

`GET /api/tempus/interesting-spots/` returns ranked, named observation sites
around one WGS 84 position. It uses a 20 km radius by default, so a minimal
request is:

```text
GET /api/tempus/interesting-spots/?longitude=18.0649&latitude=59.3293
```

Optional query parameters are `radius_m` (1–100,000, default 20,000),
`taxon_id`, `since_days` (1–365, default 30), `notable_days` (1–365, default
10), and `num_spots` (1–25, default 10).

The response includes the searched point, radius, result count, and a `spots`
array ordered by score. Each spot includes its GeoJSON location, distance from
the searched point, locality, municipality/county, species count, score
breakdown, recent notable species, explanatory highlights, and top species.
