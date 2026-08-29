from types import SimpleNamespace

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from tempus.models import Species
from tempus.services import artdatabanken as adb

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


class FakeResponse:
    def __init__(self, *, status=200, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = "" if body is None else str(body)
        self.content = b"" if body is None else b"body"

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(dict(method=method, url=url, params=params,
                               json=json, headers=headers or {}))
        return self._responses.pop(0)


def _use(testcase, *responses):
    session = FakeSession(responses)
    testcase.enterContext(_patch(adb, "_session", lambda: session))
    return session


class _patch:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


class ConfigurationTests(SimpleTestCase):
    @override_settings(ARTDATABANKEN={})
    def test_missing_key_raises_configuration_error(self):
        with self.assertRaises(adb.ArtdatabankenConfigurationError):
            adb.get_taxon(101664)

    def test_search_taxa_empty_query_short_circuits(self):
        self.assertEqual(adb.search_taxa("   "), [])

    def test_get_taxon_rejects_non_positive_id(self):
        with self.assertRaises(ValueError):
            adb.get_taxon(0)


class NormalizeSpeciesDataTests(SimpleTestCase):
    # Landskapstyper: "betydelse" wording, occasional (X) code in the name.
    LANDSCAPES = [{
        "taxonId": 201153,
        "swedishName": "hedblåvinge",
        "speciesData": [
            {"id": 663, "parentId": None, "name": "Jordbrukslandskap (J)", "significance": "Stor betydelse"},
            {"id": 662, "parentId": None, "name": "Skog (S)", "significance": "Har betydelse"},
            {"id": 999, "parentId": None, "name": "Ignorerad", "significance": "Ingen betydelse"},
        ],
    }]
    # Biotoper: "Viktig" / "Utnyttjas" / null, plain names, parentId hierarchy.
    BIOTOPES = [{
        "taxonId": 201152,
        "scientificName": "Plebejus argus",
        "speciesData": [
            {"id": 1339, "parentId": 2487, "name": "Öppna gräsmarker", "significance": "Viktig"},
            {"id": 1343, "parentId": 1339, "name": "Torra gräsmarker", "significance": "Utnyttjas"},
            {"id": 1507, "parentId": None, "name": "Människoskapad miljö", "significance": None},
        ],
    }]

    def test_landscapes_fold_and_parse_code(self):
        self.assertEqual(adb._normalize_speciesdata(self.LANDSCAPES, 201153), [
            {"id": 663, "parent_id": None, "code": "J", "name": "Jordbrukslandskap", "significance": "stor"},
            {"id": 662, "parent_id": None, "code": "S", "name": "Skog", "significance": "har"},
        ])

    def test_biotopes_fold_viktig_utnyttjas_and_keep_parent(self):
        self.assertEqual(adb._normalize_speciesdata(self.BIOTOPES, 201152), [
            {"id": 1339, "parent_id": 2487, "code": "", "name": "Öppna gräsmarker", "significance": "stor"},
            {"id": 1343, "parent_id": 1339, "code": "", "name": "Torra gräsmarker", "significance": "har"},
        ])

    def test_filters_by_taxon_id_and_tolerates_empty(self):
        self.assertEqual(adb._normalize_speciesdata(self.LANDSCAPES, 999999), [])
        self.assertEqual(adb._normalize_speciesdata(None), [])
        self.assertEqual(adb._normalize_speciesdata([]), [])

    def test_same_normaliser_backs_landscapes_and_biotopes(self):
        self.assertIs(adb._normalize_landscapes, adb._normalize_speciesdata)


@override_settings(ARTDATABANKEN=_SETTINGS)
class SpeciesDatasetEndpointTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_landscapes_and_biotopes_hit_their_datasets(self):
        session = _use(
            self,
            FakeResponse(body=[{"taxonId": 5, "speciesData": []}]),
            FakeResponse(body=[{"taxonId": 5, "speciesData": []}]),
        )
        adb.get_species_landscapes(5)
        adb.get_species_biotopes(5)
        self.assertEqual(
            session.calls[0]["url"],
            "https://api.test/info/v1/speciesdataservice/v1/speciesdata/landscapetypes",
        )
        self.assertEqual(
            session.calls[1]["url"],
            "https://api.test/info/v1/speciesdataservice/v1/speciesdata/biotopes",
        )
        self.assertEqual(session.calls[1]["params"], {"taxa": 5})


@override_settings(ARTDATABANKEN=_SETTINGS)
class UpsertSpeciesTests(TestCase):
    TAXON = {
        "taxonId": 101664,
        "category": {"value": "Species", "name": "Art"},
        "status": {"value": "Accepted"},
        "names": [
            {"name": "Anthocharis cardamines", "nameShort": "lat", "isRecommended": True},
            {"name": "aurorafjäril", "nameShort": "swe", "isRecommended": True},
        ],
    }

    def _dataset(self, name, significance, *, parent=None):
        return [{"taxonId": 101664, "speciesData": [
            {"id": 1, "parentId": parent, "name": name, "significance": significance},
        ]}]

    def test_stores_landscapes_and_biotopes(self):
        _use(
            self,
            FakeResponse(body=[self.TAXON]),
            FakeResponse(body={"info": "x"}),
            FakeResponse(body=self._dataset("Skog", "Har betydelse")),
            FakeResponse(body=self._dataset("Ädellövskog", "Viktig", parent=878)),
        )
        species = adb.upsert_species(101664)
        self.assertEqual(
            species.landscape_types,
            [{"id": 1, "parent_id": None, "code": "", "name": "Skog", "significance": "har"}],
        )
        self.assertEqual(
            species.biotopes,
            [{"id": 1, "parent_id": 878, "code": "", "name": "Ädellövskog", "significance": "stor"}],
        )
        self.assertIsNotNone(species.synced_at)

    def test_biotope_fetch_failure_is_best_effort(self):
        _use(
            self,
            FakeResponse(body=[self.TAXON]),
            FakeResponse(body={}),
            FakeResponse(body=self._dataset("Skog", "Har betydelse")),
            FakeResponse(status=502, body="down"),
        )
        species = adb.upsert_species(101664)
        self.assertEqual(len(species.landscape_types), 1)
        self.assertEqual(species.biotopes, [])  # model default, fetch skipped


@override_settings(ARTDATABANKEN=_SETTINGS)
class BulkResyncHelperTests(TestCase):
    def test_stale_species_picks_never_synced_and_old(self):
        from django.utils import timezone
        import datetime

        now = timezone.now()
        Species.objects.create(dyntaxa_taxon_id=1, scientific_name="A", synced_at=now)
        Species.objects.create(
            dyntaxa_taxon_id=2, scientific_name="B",
            synced_at=now - datetime.timedelta(days=90),
        )
        Species.objects.create(dyntaxa_taxon_id=3, scientific_name="C")

        due = adb.stale_species(older_than_days=30)
        self.assertEqual(
            sorted(due.values_list("dyntaxa_taxon_id", flat=True)), [2, 3]
        )

    def test_batch_reports_per_species_errors(self):
        Species.objects.create(dyntaxa_taxon_id=10, scientific_name="ok")
        Species.objects.create(dyntaxa_taxon_id=11, scientific_name="bad")

        def fake(tid):
            if tid == 11:
                raise adb.ArtdatabankenAPIError("GET", "/x", 502, "boom")
            return SimpleNamespace(dyntaxa_taxon_id=tid)

        with _patch(adb, "upsert_species", fake):
            results = list(
                adb.resync_species_batch(Species.objects.order_by("dyntaxa_taxon_id"))
            )
        self.assertEqual(results[0][0], 10)
        self.assertIsNone(results[0][2])
        self.assertEqual(results[1][0], 11)
        self.assertIsInstance(results[1][2], adb.ArtdatabankenAPIError)


@override_settings(ARTDATABANKEN=_SETTINGS)
class TransportTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_get_taxon_posts_id_list_and_normalizes(self):
        session = _use(self, FakeResponse(body=[{
            "taxonId": 101664,
            "parentId": 101657,
            "category": {"value": "Species", "name": "Art"},
            "status": {"value": "Accepted"},
            "names": [
                {"name": "Anthocharis cardamines", "nameShort": "lat",
                 "isRecommended": True},
                {"name": "aurorafjäril", "nameShort": "swe", "isRecommended": True},
            ],
        }]))
        taxon = adb.get_taxon(101664)
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://api.test/taxon/v1/taxa")
        self.assertEqual(call["json"], {"taxonIds": [101664]})
        self.assertEqual(call["headers"]["Ocp-Apim-Subscription-Key"], "taxon-key")
        self.assertEqual(taxon["dyntaxa_taxon_id"], 101664)
        self.assertEqual(taxon["scientific_name"], "Anthocharis cardamines")
        self.assertEqual(taxon["swedish_name"], "aurorafjäril")
        self.assertEqual(taxon["taxon_rank"], "Art")
        self.assertEqual(taxon["parent_dyntaxa_taxon_id"], 101657)
        self.assertIs(taxon["is_active"], True)

    def test_get_taxon_raises_when_not_found(self):
        _use(self, FakeResponse(body=[]))
        with self.assertRaises(adb.ArtdatabankenAPIError):
            adb.get_taxon(999999999)

    def test_search_taxa_hits_search_endpoint_and_normalizes(self):
        session = _use(self, FakeResponse(body={"data": [{
            "taxonId": 100034,
            "parentId": 200000,
            "category": {"value": "Species", "name": "Art"},
            "status": {"value": "Accepted"},
            "names": [
                {"name": "Circus cyaneus", "category": {"value": "ScientificName"},
                 "isRecommended": True},
                {"name": "blå kärrhök", "category": {"value": "SwedishName"},
                 "isRecommended": True},
            ],
        }]}))
        results = adb.search_taxa("blå kärrhök")
        self.assertEqual(session.calls[0]["url"],
                         "https://api.test/taxon/v1/taxa/search")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["dyntaxa_taxon_id"], 100034)
        self.assertEqual(results[0]["scientific_name"], "Circus cyaneus")
        self.assertEqual(results[0]["swedish_name"], "blå kärrhök")

    def test_search_taxa_returns_species_only(self):
        _use(self, FakeResponse(body={"data": [
            {"taxonId": 1, "category": {"id": 17, "value": "Species"}, "names": [
                {"name": "Plebejus idas", "category": {"value": "ScientificName"},
                 "isRecommended": True}]},
            {"taxonId": 2, "category": {"id": 14, "value": "Genus"}, "names": [
                {"name": "Plebejus", "category": {"value": "ScientificName"},
                 "isRecommended": True}]},
        ]}))
        results = adb.search_taxa("plebejus")
        self.assertEqual([r["dyntaxa_taxon_id"] for r in results], [1])

    def test_search_taxa_filters_by_ancestor_when_scoped(self):
        session = _use(
            self,
            FakeResponse(body={"data": [
                {"taxonId": 100034, "names": [
                    {"name": "Circus cyaneus", "category": {"value": "ScientificName"},
                     "isRecommended": True}]},
                {"taxonId": 999, "names": [
                    {"name": "Aurora aurora", "category": {"value": "ScientificName"},
                     "isRecommended": True}]},
            ]}),
            FakeResponse(body={"taxonIds": [0, 4000104, 6000000]}),   # 100034 parents
            FakeResponse(body={"taxonIds": [0, 12345]}),              # 999 parents
        )
        results = adb.search_taxa("aurora", under_taxon_id=4000104)
        self.assertEqual([r["dyntaxa_taxon_id"] for r in results], [100034])
        self.assertEqual(session.calls[1]["url"],
                         "https://api.test/taxon/v1/taxa/100034/parentids")

    def test_api_error_is_raised_with_status(self):
        _use(self, FakeResponse(status=429, body="slow down"))
        with self.assertRaises(adb.ArtdatabankenAPIError) as ctx:
            adb.get_taxon(1)
        self.assertEqual(ctx.exception.status, 429)

    def test_count_observations_parses_shapes(self):
        _use(self, FakeResponse(body={"count": 7}))
        self.assertEqual(adb.count_observations({}), 7)
        _use(self, FakeResponse(body={"totalCount": 9}))
        self.assertEqual(adb.count_observations({}), 9)

    def test_search_observations_validates_limits(self):
        with self.assertRaises(ValueError):
            adb.search_observations({}, take=5000)
        with self.assertRaises(ValueError):
            adb.search_observations({}, skip=9900, take=500)

    def test_iter_observations_pages_then_stops(self):
        session = _use(
            self,
            FakeResponse(body={"totalCount": 3, "records": [{"i": 1}, {"i": 2}]}),
            FakeResponse(body={"totalCount": 3, "records": [{"i": 3}]}),
        )
        got = [r["i"] for r in adb.iter_observations({}, page_size=2)]
        self.assertEqual(got, [1, 2, 3])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["url"],
                         "https://api.test/sos/v1/Observations/Search")
