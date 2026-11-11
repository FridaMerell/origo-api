import datetime

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from tempus.models import GeoArea, Phenogram, Species, SpeciesCategory, SpeciesCategoryMembership
from tempus.services import artdatabanken as adb
from tempus.services import diversity, phenogram

_SETTINGS = {
    "SPECIES_OBSERVATION_URL": "https://api.test/sos/v1",
    "TAXON_SERVICE_URL": "https://api.test/taxon/v1",
    "SPECIES_INFORMATION_URL": "https://api.test/info/v1",
    "SUBSCRIPTION_KEY_SOS": "sos-key",
    "SUBSCRIPTION_KEY_TAXON": "taxon-key",
    "SUBSCRIPTION_KEY_SPECIES_INFORMATION": "info-key",
    "TIMEOUT": 5,
    "USER_AGENT": "test",
}

TODAY = datetime.date(2026, 6, 15)
TAXON = 101664
GROUP = 3000188
TOP_GROUP = 4000104

SWEDEN = {
    "type": "MultiPolygon",
    "coordinates": [[[[11.0, 55.0], [24.0, 55.0], [24.0, 69.0], [11.0, 69.0], [11.0, 55.0]]]],
}


def _spring_records():
    """Eight years of records, weeks 18-26, triangular peak at week 22."""
    records = []
    for year in range(2019, 2027):
        for week in range(18, 27):
            day = datetime.date.fromisocalendar(year, week, 3)
            for i in range(10 - abs(22 - week)):
                records.append({
                    "taxon": {"id": TAXON},
                    "event": {"startDate": day.isoformat()},
                    "location": {
                        "decimalLatitude": 59.0 + week * 0.1,
                        "decimalLongitude": 17.0 + i * 0.1,
                    },
                })
    return records


class _FakeResponse:
    def __init__(self, body, status=200, text="ok"):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.text = text
        self.content = b"body"

    def json(self):
        return self._body


class _Session:
    def __init__(self, records, max_zoom=99, presence="Bofast och reproducerande", history="Spontan"):
        self._records = records
        self._max_zoom = max_zoom
        self._presence = {"swedishPresence": presence, "immigrationHistory": history}
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "params": params})
        if url.endswith("/Observations/Search"):
            skip = (params or {}).get("skip", 0)
            take = (params or {}).get("take", 100)
            return _FakeResponse({
                "totalCount": len(self._records),
                "records": self._records[skip:skip + take],
            })
        if url.endswith("/Observations/GeoGridAggregation"):
            if params["zoom"] > self._max_zoom:
                return _FakeResponse({}, 400, "The number of cells that can be returned is too large.")
            # the species: 3 cells a year; its group: 40 cells, the species' 3
            # among them with 2 of the group's taxa each, the others with 10
            if json["taxon"]["ids"] == [TAXON]:
                cells = [(i, 5, 1) for i in range(3)]
            else:
                cells = [(i, 50, 2 if i < 3 else 10) for i in range(40)]
            return _FakeResponse({"gridCells": [
                {"x": 1000 + i, "y": 2000, "observationsCount": reports, "taxaCount": taxa}
                for i, reports, taxa in cells
            ]})
        if url.endswith("/speciesdata/taxonomy"):
            return _FakeResponse([{"speciesData": self._presence, "taxonId": TAXON}])
        if url.endswith("/Observations/Count"):
            # the species' group is reported a tenth as much as the top group
            return _FakeResponse({"count": 1_000 if json["taxon"]["ids"] == [GROUP] else 10_000})
        raise AssertionError(f"unexpected URL {url}")

    def search_calls(self):
        return [c for c in self.calls if c["url"].endswith("/Observations/Search")]

    def grid_calls(self, taxon_id):
        return [
            c for c in self.calls
            if c["url"].endswith("/Observations/GeoGridAggregation") and c["json"]["taxon"]["ids"] == [taxon_id]
        ]


class _patch:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


@override_settings(ARTDATABANKEN=_SETTINGS)
class BuildPhenogramTests(SimpleTestCase):
    """build_phenogram is pure compute - no DB, no cache."""

    def _build(self, records=None, **kwargs):
        session = _Session(_spring_records() if records is None else records)
        self.enterContext(_patch(adb, "_session", lambda: session))
        return phenogram.build_phenogram(taxon_id=TAXON, today=TODAY, **kwargs), session

    def test_shape_and_peak(self):
        result, _ = self._build()
        self.assertEqual(len(result["weeks"]), 52)
        self.assertEqual([w["week"] for w in result["weeks"]], list(range(1, 53)))
        self.assertEqual(result["peak_week"], 22)
        self.assertEqual(result["years_present"], 8)
        self.assertLessEqual(result["activity_window"]["start_week"], 20)
        self.assertGreaterEqual(result["activity_window"]["end_week"], 24)
        window = result["season_window_days"]
        self.assertLess(window["start_day_of_year"], window["end_day_of_year"])
        self.assertEqual(window["confidence"], 1.0)

    def test_geometry_adds_geographics_filter(self):
        _, session = self._build()
        self.assertNotIn("geographics", session.calls[0]["json"])
        session2 = _Session(_spring_records())
        with _patch(adb, "_session", lambda: session2):
            phenogram.build_phenogram(taxon_id=TAXON, geometry=SWEDEN, today=TODAY)
        self.assertEqual(session2.calls[0]["json"]["geographics"]["geometries"], [SWEDEN])
        self.assertEqual(
            session2.calls[0]["json"]["taxon"],
            {"ids": [TAXON], "includeUnderlyingTaxa": True},
        )

    def test_declustering_collapses_a_mob(self):
        mob = [
            {
                "taxon": {"id": TAXON},
                "event": {"startDate": "2026-06-10"},
                "location": {"decimalLatitude": 59.0, "decimalLongitude": 17.0},
            }
            for _ in range(200)
        ]
        declustered, _ = self._build(records=mob, decluster=True)
        self.assertEqual(declustered["sample_count"], 1)
        raw, _ = self._build(records=mob, decluster=False)
        self.assertEqual(raw["sample_count"], 200)

    def test_rejects_bad_taxon_id(self):
        with self.assertRaises(ValueError):
            phenogram.build_phenogram(taxon_id=0, today=TODAY)

    @override_settings(ARTDATABANKEN={})
    def test_missing_config_raises(self):
        with self.assertRaises(adb.ArtdatabankenConfigurationError):
            phenogram.build_phenogram(taxon_id=TAXON, today=TODAY)

    def test_max_records_caps_the_crawl(self):
        many = _spring_records() * 3
        result, _ = self._build(records=many, max_records=100)
        self.assertEqual(result["record_count"], 100)
        self.assertTrue(result["record_limit_hit"])


@override_settings(ARTDATABANKEN=_SETTINGS)
class GetPhenogramTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.species = Species.objects.create(
            dyntaxa_taxon_id=TAXON, scientific_name="Anthocharis cardamines"
        )
        self.area = GeoArea.objects.create(
            name="Sverige", kind=GeoArea.Kind.COUNTRY, country_code="SE", geometry=SWEDEN
        )
        group = SpeciesCategory.objects.create(label="Fjärilar", taxon_id=GROUP, is_primary=True)
        child = SpeciesCategory.objects.create(label="Vitfjärilar", parent_category=group)
        SpeciesCategoryMembership.objects.create(category=child, species=self.species)
        SpeciesCategory.objects.create(label="Fåglar", taxon_id=TOP_GROUP, is_primary=True)

    def _session(self):
        session = _Session(_spring_records())
        self.enterContext(_patch(adb, "_session", lambda: session))
        return session

    def test_builds_and_persists_on_first_call(self):
        self._session()
        pg = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.assertIsInstance(pg, Phenogram)
        self.assertEqual(pg.peak_week, 22)
        self.assertEqual(len(pg.weeks), 52)
        self.assertEqual(Phenogram.objects.count(), 1)
        self.assertEqual(pg.geo_area, self.area)
        # measured against the primary group above the species' own category,
        # over three whole years: 3 of 40 cells, weighted by the group's taxa
        # per cell (2 in the species' cells, 10 in the others)
        basis = pg.significance_basis
        self.assertEqual(basis["group"], GROUP)
        self.assertEqual(basis["years"], [2023, 2024, 2025])
        self.assertEqual(basis["species_cells"], 9)
        self.assertEqual(basis["group_cells"], 120)
        self.assertEqual(basis["spread"], round(6 / 376, 6))
        self.assertEqual(basis["rarity"], diversity.significance_from_spread(6 / 376, 120))
        # a group reported a tenth as much as the top one
        self.assertEqual(basis["relevance"], 0.75)
        self.assertEqual(pg.significance, round(basis["rarity"] * basis["relevance"], 3))

    def test_species_without_a_primary_group_has_no_significance(self):
        session = self._session()
        SpeciesCategoryMembership.objects.filter(species=self.species).delete()
        pg = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.assertIsNone(pg.significance)
        self.assertEqual(pg.significance_basis, {})
        self.assertEqual(session.grid_calls(TAXON), [])

    def test_casual_introduced_species_has_no_significance(self):
        session = _Session(_spring_records(), presence="Tillfällig, ej reproducerande",
                           history="Aktivt införd efter år 1800")
        self.enterContext(_patch(adb, "_session", lambda: session))
        pg = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.assertIsNone(pg.significance)
        self.assertEqual(pg.significance_basis["immigration_history"], "Aktivt införd efter år 1800")
        self.assertEqual(session.grid_calls(TAXON), [])

    def test_vagrant_that_came_on_its_own_keeps_significance(self):
        session = _Session(_spring_records(), presence="Tillfällig, ej reproducerande", history="Spontan")
        self.enterContext(_patch(adb, "_session", lambda: session))
        pg = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.assertIsNotNone(pg.significance)

    def test_group_counts_are_shared_between_builds(self):
        session = self._session()
        phenogram.get_phenogram(self.species, self.area, today=TODAY)
        phenogram.get_phenogram(self.species, self.area, refresh=True, today=TODAY)
        self.assertEqual(len(session.grid_calls(GROUP)), 3)
        self.assertEqual(len(session.grid_calls(TAXON)), 6)

    def test_area_too_large_for_the_finest_grid_uses_a_coarser_one(self):
        session = _Session(_spring_records(), max_zoom=phenogram.SIGNIFICANCE_GRID_ZOOM - 1)
        self.enterContext(_patch(adb, "_session", lambda: session))
        pg = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        coarser = phenogram.SIGNIFICANCE_GRID_ZOOM - 1
        self.assertEqual(pg.significance_basis["zoom"], [coarser] * 3)
        self.assertEqual(pg.significance_basis["spread"], round(6 / 376, 6))
        # the species is counted only at the zoom its group was
        self.assertEqual([c["params"]["zoom"] for c in session.grid_calls(TAXON)], [coarser] * 3)

    def test_second_call_reads_the_row_without_crawling(self):
        session = self._session()
        first = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        second = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(len(session.search_calls()), 1)

    def test_refresh_rebuilds_the_same_row(self):
        session = self._session()
        first = phenogram.get_phenogram(self.species, self.area, today=TODAY)
        again = phenogram.get_phenogram(
            self.species, self.area, refresh=True, today=TODAY
        )
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Phenogram.objects.count(), 1)
        self.assertEqual(len(session.search_calls()), 2)

    def test_whole_range_row_when_no_area(self):
        self._session()
        pg = phenogram.get_phenogram(self.species, None, today=TODAY)
        self.assertIsNone(pg.geo_area_id)
        self.assertEqual(Phenogram.objects.filter(geo_area__isnull=True).count(), 1)
        # the whole-range value is the species' value for the whole country
        self.assertIsNotNone(pg.significance)
        self.species.refresh_from_db()
        self.assertEqual(self.species.significance, pg.significance)

    def test_area_row_leaves_the_species_value(self):
        self._session()
        phenogram.get_phenogram(self.species, self.area, today=TODAY)
        self.species.refresh_from_db()
        self.assertIsNone(self.species.significance)
