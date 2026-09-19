"""Generate the static whole-country overview file, once, offline.

    python manage.py generate_country_overview

Builds tempus/data/country_overview.json: Sweden's outline (real coastline
detail, only the smallest specks dropped), major lakes and rivers, a
hand-drawn land-use overview (see LAND_REGIONS — not live data; every
CORINE-backed version of this tried here was too slow, too much data, or
rendered as an artificial-looking grid), a hardcoded list of major cities,
and the basemap config from settings. This file is what CountryOverviewView
serves — the country's shape barely changes, so there is no reason to fetch
and reprocess it on every request.

The outline comes from Natural Earth's public-domain 1:10m Admin 0 land
dataset (its most detailed tier), not from Lantmäteriet. Two Lantmäteriet
sources were tried and rejected for this specific purpose: "Kommun, Län och
Rike Direkt" (the administrative county/country boundaries) returns
jurisdictional area, which extends into territorial water and does not match
actual land area; and "Marktäcke Direkt"'s full-resolution `markytor`
land-cover collection is accurate but far too large to fetch for a whole
country just to build this outline. Natural Earth's coarser 1:50m/1:110m
tiers were tried and rejected too: both throw away real coastline and lake
detail (narrow bays, inlets) before the file is ever downloaded, which is not
what is wanted here — 1:10m is used deliberately to keep that detail.

Commit the regenerated file when Natural Earth publishes a new edition, or
when the thresholds below are retuned; there is no scheduled regeneration.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Natural Earth 1:10m Admin 0 Countries, public domain — the most detailed
# tier, used deliberately: a heavily-generalised silhouette is not what is
# wanted here, real coastline detail (skerries, inlets) is. A stable mirror
# of the official Natural Earth data as plain GeoJSON, so no shapefile/GDAL
# dependency is needed to read it.
NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_admin_0_countries.geojson"
)

# Natural Earth 1:10m Lakes, public domain — same tier as the outline above,
# for the same reason: real detail, not a hand-drawn or over-smoothed shape.
NATURAL_EARTH_LAKES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_lakes.geojson"
)

# Sweden's largest cities by population (2020s estimates). Hardcoded: this is
# a small, stable, well-known set of public facts, not something worth an
# API round trip or a database table.
MAJOR_CITIES = [
    {"name": "Stockholm", "coordinates": [18.0686, 59.3293]},
    {"name": "Göteborg", "coordinates": [11.9746, 57.7089]},
    {"name": "Malmö", "coordinates": [13.0007, 55.6050]},
    {"name": "Uppsala", "coordinates": [17.6389, 59.8586]},
    {"name": "Västerås", "coordinates": [16.5528, 59.6099]},
    {"name": "Örebro", "coordinates": [15.2066, 59.2741]},
    {"name": "Linköping", "coordinates": [15.6214, 58.4108]},
    {"name": "Helsingborg", "coordinates": [12.6945, 56.0465]},
    {"name": "Jönköping", "coordinates": [14.1618, 57.7826]},
    {"name": "Norrköping", "coordinates": [16.1826, 58.5877]},
    {"name": "Lund", "coordinates": [13.1910, 55.7047]},
    {"name": "Umeå", "coordinates": [20.2630, 63.8258]},
    {"name": "Gävle", "coordinates": [17.1413, 60.6749]},
    {"name": "Sundsvall", "coordinates": [17.3069, 62.3908]},
    {"name": "Luleå", "coordinates": [22.1567, 65.5848]},
]

# Rough conversion at Swedish latitudes, used only to turn a human km²
# threshold into a degrees² one; not geodetically precise.
KM2_PER_DEGREE2 = 5000

# Sweden's largest lakes, looked up by name in Natural Earth's lakes dataset
# (real surveyed geometry, not a schematic shape). Just the name list is
# hardcoded — same reasoning as MAJOR_CITIES: Lantmäteriet's markytor
# collection has no area or name property (confirmed against its
# queryables), so identifying "the big ones" would otherwise mean downloading
# every lake and stream in the country - tens of thousands of features - just
# to compute areas locally. A handful of well-known, stable names is the
# honest, cheap alternative; the shape itself comes from Natural Earth.
MAJOR_LAKE_NAMES = ["Vänern", "Vättern", "Mälaren", "Hjälmaren", "Storsjön", "Siljan"]

# Sweden's largest rivers: name, and a handful of points roughly tracing
# source to mouth. Schematic, not surveyed hydrography - a straight-ish path
# through a few well-known points is enough to be recognisable at
# whole-country scale, and honest about not being more than that.
MAJOR_RIVERS = [
    {"name": "Göta älv / Klarälven", "path": [[12.5, 60.5], [12.2, 59.0], [11.9, 57.7]]},
    {"name": "Dalälven", "path": [[14.0, 61.0], [16.0, 60.6], [17.4, 60.6]]},
    {"name": "Ångermanälven", "path": [[15.0, 64.0], [16.5, 63.3], [17.9, 62.8]]},
    {"name": "Torneälven", "path": [[20.0, 68.4], [22.2, 67.0], [24.15, 65.85]]},
]

# Sweden's real bounds, with margin: lon ~11-24.2, lat ~55.1-69.1.
SWEDEN_BBOX = (10.0, 54.5, 25.0, 70.0)

# This is decoration for a whole-country map, not a land-use survey — the
# same spirit as MAJOR_RIVERS above: a handful of hand-drawn, approximate
# regions, not surveyed or fetched data. Every live-data approach tried here
# (per-parcel CORINE dissolve, a CORINE grid classified by presence, a
# CORINE grid classified by area-dominance) either transferred far too much
# data, took too long, or rendered as a blocky, artificial-looking grid —
# none of that is worth it for what is explicitly just a rough visual
# impression at whole-country zoom. `kind` values here are intentionally
# broader than the live CORINE/Lantmäteriet `objekttyp_group`
# (`forest`/`agriculture`) so the map can show more visual variety
# (dense forest vs. general forest vs. mountains) than that binary split.
# Listed first, in priority order: small, specific, well-known locales that
# should read as themselves rather than get absorbed into whichever broad
# region happens to cover that area — the difference-against-claimed logic
# in _build_land_cover_overview makes an EARLIER entry win, so these must
# come before the broad regions below for that to hold.
LAND_REGIONS = [
    {
        # Öland's Stora Alvaret: a large, well-known limestone-pavement
        # grassland, distinct from ordinary farmland or forest.
        "name": "Stora Alvaret (Öland)",
        "kind": "alvar",
        "smooth": 0.04,
        "path": [
            [16.55, 56.28], [16.75, 56.25], [16.90, 56.35], [16.85, 56.55],
            [16.70, 56.65], [16.55, 56.55], [16.48, 56.40], [16.55, 56.28],
        ],
    },
    {
        # Gotland's alvar areas, concentrated in the north (around
        # Lummelunda/Fårö) and a smaller patch near Sudret in the south.
        "name": "Gotlands alvarmark",
        "kind": "alvar",
        "smooth": 0.04,
        "path": [
            [18.55, 57.75], [18.75, 57.70], [18.95, 57.80], [18.95, 57.92],
            [18.75, 57.95], [18.55, 57.88], [18.55, 57.75],
        ],
    },
    {
        # Skåne's beech forests: Söderåsen and the Kullaberg peninsula in
        # the northwest, and a second, smaller patch around Österlen in the
        # southeast — Sweden's best-known broadleaf/deciduous forest areas.
        "name": "Söderåsen/Kullaberg (bokskog)",
        "kind": "broadleaf_forest",
        "smooth": 0.04,
        "path": [
            [12.75, 56.05], [13.15, 55.98], [13.35, 56.08], [13.20, 56.20],
            [12.90, 56.20], [12.70, 56.15], [12.75, 56.05],
        ],
    },
    {
        "name": "Österlen (bokskog)",
        "kind": "broadleaf_forest",
        "smooth": 0.04,
        "path": [
            [14.05, 55.55], [14.30, 55.50], [14.45, 55.62], [14.35, 55.75],
            [14.10, 55.72], [14.00, 55.63], [14.05, 55.55],
        ],
    },
    {
        # A genuinely NARROW band along the Norway border (real alpine
        # terrain above the tree line is a small fraction of the country,
        # not a wide swath) — Idre/Sylarna in the south up to the
        # Treriksröset/Kebnekaise area in the north, then back down its
        # inner (eastern) edge, offset only ~0.5-1.0° east of the western
        # edge at any given latitude. An earlier version was roughly 2-3x
        # this wide and covered far more of the country than actual
        # mountain terrain does.
        "name": "Fjällkedjan",
        "kind": "mountains",
        "path": [
            [12.2, 61.0], [12.0, 61.6], [12.6, 62.3], [12.2, 63.0], [12.6, 63.6],
            [12.1, 64.3], [12.6, 65.0], [12.9, 65.6], [12.5, 66.2], [13.0, 66.8],
            [12.6, 67.4], [13.2, 68.0], [12.6, 68.5], [13.4, 69.0], [14.0, 69.3],
            [14.8, 68.7], [14.3, 68.0], [14.6, 67.3], [14.0, 66.6], [14.3, 66.0],
            [13.7, 65.3], [13.9, 64.6], [13.3, 64.0], [13.5, 63.3], [13.0, 62.6],
            [13.2, 62.0], [12.9, 61.4], [12.6, 61.0], [12.2, 61.0],
        ],
    },
    {
        # The southern and eastern lowland plains: Skåne, the Halland/
        # Blekinge/Kalmar coast, Östergötland/Västergötland, and — pushed
        # further north/east than a strict "southern plains" reading —
        # Södermanland/Västmanland/Uppland (Mälardalen) and Gotland, plus —
        # pushed further WEST than the original reading — the Göteborg/
        # Västra Götaland plains. Per Jordbruksverket's 2022 land-use
        # statistics (jordbruksverket.se, "Jordbruksmarkens användning
        # 2022"), Västra Götaland and Skåne together are Sweden's two
        # largest agricultural counties by a wide margin (1,012,600 ha
        # combined) — an earlier version of this polygon stopped around
        # lon 11.7-12.0 and left the whole Västra Götaland plain (west of
        # that) to the generic forest region, which is the opposite of what
        # the real land-use data shows. Placed ahead of the two broad
        # forest zones below in priority: this shape was hand-fit carefully
        # (including the Mälardalen/Gotland/Västra Götaland extensions), so
        # it should win over the generic forest zones in its own footprint
        # rather than the other way around.
        "name": "Sydsvenska och mellansvenska slättbygden",
        "kind": "agriculture",
        "path": [
            [12.6, 55.35], [13.4, 55.3], [14.2, 55.4], [14.5, 55.9], [14.3, 56.5],
            [15.3, 56.2], [16.0, 56.6], [16.4, 57.3], [17.2, 56.9], [19.4, 56.8],
            [19.4, 58.0], [17.0, 58.0], [16.6, 58.6], [17.6, 59.1], [18.6, 59.5],
            [17.8, 60.0], [16.4, 60.1], [15.2, 59.7], [15.0, 58.7], [14.0, 58.6],
            [13.2, 58.3], [12.2, 58.6], [11.2, 58.3], [11.0, 57.5], [11.3, 56.7],
            [11.7, 56.3], [12.0, 55.7], [12.6, 55.35],
        ],
    },
    {
        # Everything roughly north of Svealand: covers Norrland's inland AND
        # coastal forest generously — deliberately a big, loose, FLAT-BOTTOMED
        # rectangle (lon 11-24.5, lat 60.6-69.3) rather than an attempt to
        # hug Fjällkedjan's, the coastline's, or the plains region's exact
        # edge. Two earlier attempts at precisely matching neighbouring
        # regions' boundaries both left real gaps (confirmed live: first a
        # 2-6 deg² hole rendered as "mountains", then — after that fix — a
        # sizeable belt around Gästrikland/southern Hälsingland left
        # uncovered because this region's own southern edge sloped upward
        # with longitude instead of staying flat, undershooting the plains
        # region's northern reach further east). A flat southern edge at a
        # single, generously low latitude removes that whole class of bug:
        # the difference-against-claimed logic (see _build_land_cover_overview)
        # carves the exact boundary against whatever Fjällkedjan/the plains
        # region already claimed, so this rectangle only needs to be at
        # least as far south as anything it should ever lose to them, not
        # precisely matched to their shape.
        "name": "Norrlands inland",
        "kind": "dense_forest",
        "path": [
            [11.0, 60.6], [11.0, 69.3], [24.5, 69.3], [24.5, 60.6], [11.0, 60.6],
        ],
    },
    {
        # Everything else in the centre/south not already claimed:
        # Värmland, Dalarna, Bergslagen, the Småland highlands. Same
        # "generous envelope, let the code carve the exact boundary" logic
        # as Norrlands inland above — this is genuinely just "whatever
        # central/southern land the more specific regions above didn't
        # claim", not a precisely-bounded region in its own right.
        "name": "Svealand/Götalands skogsbygd",
        "kind": "forest",
        "path": [
            [10.5, 56.0], [10.5, 61.2], [17.5, 61.2], [17.5, 56.0], [10.5, 56.0],
        ],
    },
]


class Command(BaseCommand):
    help = "Generate tempus/data/country_overview.json, once, from Natural Earth."

    def add_arguments(self, parser):
        parser.add_argument(
            "--outline-simplify-tolerance",
            type=float,
            default=0.001,
            help=(
                "Degrees; higher is coarser. Default 0.001 (~100 m) — light "
                "cleanup only, real coastline/lake detail (inlets, narrow "
                "bays) is kept rather than smoothed away."
            ),
        )
        parser.add_argument(
            "--outline-min-island-km2",
            type=float,
            default=1.0,
            help="Drop outline polygons smaller than this (drops the very smallest specks only).",
        )
        parser.add_argument(
            "--natural-earth-url",
            default=NATURAL_EARTH_URL,
            help="Source GeoJSON for the outline (Natural Earth Admin 0 countries).",
        )
        parser.add_argument(
            "--skip-land-cover",
            action="store_true",
            help="Skip the hand-drawn land-cover overview (outline/waterways/cities only).",
        )

    def handle(self, *args, **options):
        waterways, lake_shapes = self._build_waterways(options["outline_simplify_tolerance"])
        outline, land_shape = self._build_outline(
            options["outline_simplify_tolerance"],
            options["outline_min_island_km2"],
            options["natural_earth_url"],
            lake_shapes,
        )

        data = {
            "basemap": getattr(settings, "TEMPUS_MAP_BASEMAP", {}),
            "outline": outline,
            "waterways": waterways,
            "cities": MAJOR_CITIES,
        }
        if not options["skip_land_cover"]:
            data["land_cover"] = self._build_land_cover_overview(land_shape)

        out_path = Path(settings.BASE_DIR) / "tempus" / "data" / "country_overview.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))

    def _build_outline(
        self,
        tolerance: float,
        min_island_km2: float,
        natural_earth_url: str,
        lake_shapes: list,
    ):
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union

        feature = self._fetch_sweden_feature(natural_earth_url)
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            raise CommandError("Natural Earth Sweden feature has no geometry.")
        whole_raw = shape(geometry)
        raw_parts = list(whole_raw.geoms) if whole_raw.geom_type == "MultiPolygon" else [whole_raw]

        # Filter by ORIGINAL area first, before any simplification: deciding
        # what to keep by post-simplify area would let a coarse tolerance
        # collapse a real island (e.g. narrow Öland) to near-nothing and then
        # get discarded by the area filter for the wrong reason.
        min_area = min_island_km2 / KM2_PER_DEGREE2
        kept_raw = [part for part in raw_parts if part.area >= min_area]
        self.stdout.write(
            f"Outline: kept {len(kept_raw)}/{len(raw_parts)} polygons by original area "
            f"(dropped smaller than {min_island_km2} km2)"
        )
        if not kept_raw:
            raise CommandError("Area filter dropped every outline polygon; lower --outline-min-island-km2.")

        whole_kept = unary_union(kept_raw)

        # Simplify the kept parts TOGETHER, as one union, not independently -
        # simplifying touching parts on their own lets their shared border
        # drift apart differently for each part.
        generalised = whole_kept.simplify(tolerance, preserve_topology=True)
        if generalised.is_empty:
            self.stdout.write(
                self.style.WARNING(
                    f"  outline collapsed to empty at tolerance={tolerance}; keeping it unsimplified instead"
                )
            )
            generalised = whole_kept

        # Guard against simplify silently dropping a whole kept part (can
        # happen to a small one even though the area filter passed it):
        # check each part's centroid is still covered, and if not, union its
        # original, unsimplified geometry back in.
        for part in kept_raw:
            if not generalised.intersects(part.representative_point()):
                self.stdout.write(
                    self.style.WARNING(
                        f"  a {part.area * KM2_PER_DEGREE2:.0f} km2 part vanished during simplify; "
                        "adding it back unsimplified"
                    )
                )
                generalised = unary_union([generalised, part])

        # Sweden's coastline and Mälaren's many narrow bays are genuinely
        # this convoluted in reality — that is real detail, not noise, so it
        # is kept rather than smoothed into a rounder-looking but less
        # accurate shape. Only fix outright invalid geometry (e.g. a
        # self-intersection simplify can leave behind), never reshape valid
        # geometry to look tidier.
        if not generalised.is_valid:
            generalised = generalised.buffer(0)

        # Cut the real lake shapes out of the land outline so the two layers
        # do not both claim the same area (double-counted land under a lake,
        # or a visible sliver/gap where two independently-simplified edges
        # do not quite line up). lake_shapes is already simplified and
        # smoothed by the caller (see _build_waterways) at this same
        # tolerance. Do NOT simplify or smooth again after this cut: that
        # would move the hole's boundary away from the lake polygon rendered
        # separately in `waterways`, producing exactly the mismatched
        # double-edge this cut exists to avoid.
        if lake_shapes:
            generalised = generalised.difference(unary_union(lake_shapes))

        feature_dict = {"type": "Feature", "properties": {"kind": "country"}, "geometry": mapping(generalised)}
        return feature_dict, generalised

    def _fetch_sweden_feature(self, natural_earth_url: str) -> dict:
        """Download Natural Earth's Admin 0 countries file and return Sweden's feature.

        The whole file (every country, at 1:10m — Natural Earth's most
        detailed tier) is tens of MB — a one-time download for this offline
        generation step, not a per-request cost, and still far smaller than
        fetching Lantmäteriet's full-resolution `markytor` land-cover
        collection for the whole country would be.
        """
        import requests

        try:
            response = requests.get(natural_earth_url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not download Natural Earth data: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CommandError("Natural Earth response was not valid JSON.") from exc

        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            iso_a2 = properties.get("ISO_A2") or properties.get("iso_a2")
            iso_a3 = properties.get("ISO_A3") or properties.get("adm0_a3")
            name = properties.get("NAME") or properties.get("name")
            if iso_a2 == "SE" or iso_a3 == "SWE" or name == "Sweden":
                self.stdout.write("Found Sweden feature in Natural Earth data")
                return feature
        raise CommandError("Sweden feature not found in Natural Earth data.")

    def _fetch_named_lakes(self, lakes_url: str, names: list[str]) -> dict[str, dict]:
        """Download Natural Earth's lakes file and return each requested lake's feature by name.

        Matches case- and diacritic-insensitively (Natural Earth's `name`
        property is expected to carry the original Swedish name unchanged,
        but this avoids depending on exact casing/encoding).
        """
        import unicodedata

        import requests

        def fold(text: str) -> str:
            normalised = unicodedata.normalize("NFKD", text)
            return "".join(c for c in normalised if not unicodedata.combining(c)).casefold()

        try:
            response = requests.get(lakes_url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not download Natural Earth lakes data: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CommandError("Natural Earth lakes response was not valid JSON.") from exc

        wanted = {fold(name): name for name in names}
        found: dict[str, dict] = {}
        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            candidates = [
                properties.get(key)
                for key in ("name", "name_en", "name_alt", "namealt")
                if properties.get(key)
            ]
            for candidate in candidates:
                folded = fold(str(candidate))
                if folded in wanted and wanted[folded] not in found:
                    found[wanted[folded]] = feature
                    break

        missing = [name for name in names if name not in found]
        if missing:
            raise CommandError(f"Lake(s) not found in Natural Earth lakes data: {', '.join(missing)}")
        self.stdout.write(f"Found {len(found)}/{len(names)} named lakes in Natural Earth data")
        return found

    def _build_waterways(self, tolerance: float) -> tuple[dict, list]:
        """Build lake/river features.

        Lakes come from Natural Earth's real, surveyed lake geometry (looked
        up by name — see MAJOR_LAKE_NAMES), not a schematic shape: once the
        outline itself is real generalised land data, a hand-drawn shape for
        the lakes sitting on top of it would be an inconsistent downgrade.
        The lakes dataset is a much more detailed tier (1:10m) than the
        outline (1:50m), so each lake is simplified to the outline's own
        tolerance here too — otherwise the rendered map carries far more
        lake-boundary detail than the land around it needs, which is slow to
        render for no visible benefit at whole-country zoom.
        Rivers remain the hardcoded schematic paths below — see MAJOR_RIVERS.

        Returns the waterways FeatureCollection dict, and the simplified lake
        shapely geometries so the outline can be cut to match them exactly
        (see _build_outline).
        """
        from shapely.geometry import LineString, mapping, shape

        lakes_by_name = self._fetch_named_lakes(NATURAL_EARTH_LAKES_URL, MAJOR_LAKE_NAMES)

        features = []
        lake_shapes = []
        for name, feature in lakes_by_name.items():
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            # Mälaren's many narrow bays are real detail, kept rather than
            # smoothed away. Only a light simplify (default tolerance ~100 m)
            # to drop redundant points, and buffer(0) purely to fix up an
            # invalid (self-intersecting) result if simplify produces one —
            # never a reshaping smoothing pass.
            lake_shape = shape(geometry).simplify(tolerance, preserve_topology=True)
            if not lake_shape.is_valid:
                lake_shape = lake_shape.buffer(0)
            lake_shapes.append(lake_shape)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "lake", "name": name},
                    "geometry": mapping(lake_shape),
                }
            )
        for river in MAJOR_RIVERS:
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "river", "name": river["name"], "approximate": True},
                    "geometry": mapping(LineString(river["path"])),
                }
            )
        self.stdout.write(
            f"Waterways: {len(lakes_by_name)} lakes (Natural Earth), "
            f"{len(MAJOR_RIVERS)} rivers (hardcoded)"
        )
        return {"type": "FeatureCollection", "features": features}, lake_shapes

    def _build_land_cover_overview(self, land_shape) -> dict:
        """Build a whole-country land-use overview from LAND_REGIONS — a
        handful of hand-drawn, approximate regions (mountains, dense
        Norrland forest, general forest, farmland plains), the same spirit
        as MAJOR_RIVERS: no live data, no API calls, nothing to fetch or
        cache. Every live-data version tried here (per-parcel CORINE
        dissolve, a CORINE grid by presence, a CORINE grid by area
        dominance) was rejected — too much data, too slow, or rendered as an
        artificial-looking grid of squares — none of which is worth it for
        what is explicitly just a rough visual impression at whole-country
        zoom, not a land-use survey.

        Each region is intersected with `land_shape` (the country outline)
        so a hand-drawn region never extends past the coastline into open
        water, and — regardless of how carefully the coordinates in
        LAND_REGIONS are drawn — each region is also cut against the union
        of every region already placed before it, so two regions can never
        overlap in the output. Hand-drawn coordinates alone cannot guarantee
        that (confirmed live: they didn't, adjacent regions visibly
        overlapped on the rendered map); this makes non-overlap a property
        of the code, not of how well the coordinates happen to line up.
        Draw LAND_REGIONS in the order regions should take priority where
        they'd otherwise overlap — an earlier entry wins (used here to let
        small, specific locales like alvar/broadleaf-forest patches win over
        the broad regions that would otherwise cover the same area).

        For the same reason, coverage of the whole country is ALSO made a
        property of the code, not of the coordinates: any part of
        `land_shape` no region ends up claiming (confirmed live: with only
        the four broad regions, all of Gotland and the Mälardalen area were
        left blank) is assigned afterwards to whichever already-placed
        region is geographically nearest, so every part of the country
        always has SOME land-use category, never a gap.
        """
        from shapely.geometry import Polygon, mapping
        from shapely.ops import unary_union

        # Round off each hand-drawn polygon's own sharp vertices (dilate
        # then erode) so it reads as a soft, natural-looking blob instead of
        # a crude straight-edged wedge. Cheap here (a handful of shapes
        # total), unlike the same operation on thousands of CORINE parcels.
        # Per-region, not a single constant: the small, specific locales
        # (alvar, broadleaf forest patches) are themselves only a few tenths
        # of a degree across, so the broad regions' rounding radius would
        # erode them down to nothing — each region's own `smooth` (default
        # 0.3, matching the broad regions) must stay well under its own
        # narrowest width.
        DEFAULT_SMOOTH = 0.3

        features = []
        shapes_list = []
        claimed = None
        for region in LAND_REGIONS:
            radius = region.get("smooth", DEFAULT_SMOOTH)
            shape = Polygon(region["path"]).buffer(radius).buffer(-radius)
            shape = shape.intersection(land_shape)
            if claimed is not None:
                shape = shape.difference(claimed)
            if shape.is_empty:
                continue
            claimed = shape if claimed is None else unary_union([claimed, shape])
            shapes_list.append(shape)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "land_cover", "name": region["name"], "objekttyp_group": region["kind"]},
                    "geometry": mapping(shape),
                }
            )

        # Coverage guarantee: assign any land no region claimed to whichever
        # region is geographically nearest, rather than leaving it out of
        # the output entirely. A single leftover area can span multiple
        # unrelated parts of the country (confirmed live: Gotland and
        # Mälardalen were both left blank at once), so each disconnected
        # piece is matched to its own nearest region independently, not the
        # leftover as a whole to one region.
        if claimed is not None and features:
            leftover = land_shape.difference(claimed)
            if not leftover.is_empty:
                leftover_parts = list(leftover.geoms) if leftover.geom_type == "MultiPolygon" else [leftover]
                for part in leftover_parts:
                    if part.area < 1e-6:
                        continue
                    nearest_index = min(range(len(shapes_list)), key=lambda i: shapes_list[i].distance(part))
                    shapes_list[nearest_index] = unary_union([shapes_list[nearest_index], part])
                    features[nearest_index]["geometry"] = mapping(shapes_list[nearest_index])

        self.stdout.write(
            f"Land cover: {len(features)} hand-drawn region(s), non-overlapping, "
            "covering the whole country (no live data)"
        )

        return {"source": "schematic", "tiers": {"overview": {"type": "FeatureCollection", "features": features}}}
