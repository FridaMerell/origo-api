import datetime

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from tempus.services import artdatabanken as adb
from tempus.services import route_planner

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
CROW, MALLARD, TIT, WARBLER = 103095, 202803, 199324, 205835
HERON, SWAN, LAPWING, CURLEW = 100001, 100002, 100003, 100004

# Precomputed rarity, as route_planner would read from the DB.
_SIGNIFICANCE = {CROW: 0.02, MALLARD: 0.15, TIT: 0.12, WARBLER: 0.9, HERON: 0.2}


def _significance_of(taxon_id):
    return _SIGNIFICANCE.get(taxon_id)

ROUTE = {
    "type": "LineString",
    "coordinates": [[18.0649, 59.3293], [17.6389, 59.8586]],  # Sthlm -> Uppsala
}

# Live SOS TaxonAggregation shape: flat taxonId + observationCount, no names.
_TAXON_AGG = {"skip": 0, "take": 50, "totalCount": 4, "records": [
    {"taxonId": CROW, "observationCount": 900, "lastSighting": "2026-06-14T09:00:00+02:00"},
    {"taxonId": MALLARD, "observationCount": 300, "lastSighting": "2026-06-13T09:00:00+02:00"},
    {"taxonId": TIT, "observationCount": 200, "lastSighting": "2026-06-10T09:00:00+02:00"},
    {"taxonId": WARBLER, "observationCount": 2, "lastSighting": "2026-06-13T09:00:00+02:00"},
]}


# Dyntaxa POST /taxa batch (enrichment): names + redlistCategory.
def _taxon_dto(tid, sci, swe="", redlist=None):
    dto = {"taxonId": tid, "names": [
        {"name": sci, "nameShort": "lat", "isRecommended": True}]}
    if swe:
        dto["names"].append({"name": swe, "nameShort": "swe", "isRecommended": True})
    if redlist:
        dto["redlistCategory"] = redlist
    return dto


_TAXA = [
    _taxon_dto(CROW, "Corvus cornix", "kråka"),
    _taxon_dto(MALLARD, "Anas platyrhynchos", "gräsand"),
    _taxon_dto(TIT, "Parus major", "talgoxe"),
    # Dyntaxa returns the status as a Swedish phrase, not the bare code
    _taxon_dto(WARBLER, "Acrocephalus paludicola", "vattensångare",
               redlist="Starkt hotad (EN)"),
    _taxon_dto(HERON, "Ardea cinerea", "gråhäger"),
    _taxon_dto(SWAN, "Cygnus olor", "knölsvan"),
    _taxon_dto(LAPWING, "Vanellus vanellus", "tofsvipa", redlist="Sårbar (VU)"),
    _taxon_dto(CURLEW, "Numenius arquata", "storspov", redlist="Starkt hotad (EN)"),
]


def _rec(tid, day, locality, location_id, lat=59.5, lon=17.8):
    return {
        "taxon": {"id": tid},
        "event": {"startDate": f"2026-06-{day:02d}T07:00:00+02:00"},
        "location": {
            "locality": locality, "locationId": location_id,
            "decimalLatitude": lat, "decimalLongitude": lon,
            "county": {"featureId": "1", "name": "Uppsala"},
            "municipality": {"featureId": "380", "name": "Uppsala"},
        },
    }


_SITE = "urn:lsid:artportalen.se:site:1"
_STREET = "urn:lsid:artportalen.se:site:2"

# One rich named site ("Fågelsjön") + a thin one ("Villagatan 3") below the
# min-taxa bar that must not be picked.
_SEARCH = {"totalCount": 11, "records": [
    _rec(WARBLER, 13, "Fågelsjön, Srm", _SITE),
    _rec(CURLEW, 13, "Fågelsjön, Srm", _SITE),
    _rec(LAPWING, 12, "Fågelsjön, Srm", _SITE),
    _rec(HERON, 12, "Fågelsjön, Srm", _SITE),
    _rec(SWAN, 11, "Fågelsjön, Srm", _SITE),
    _rec(MALLARD, 10, "Fågelsjön, Srm", _SITE),
    _rec(TIT, 9, "Fågelsjön, Srm", _SITE),
    _rec(CROW, 8, "Fågelsjön, Srm", _SITE),
    _rec(CROW, 14, "Villagatan 3, Srm", _STREET, lat=59.6, lon=17.9),
    _rec(TIT, 13, "Villagatan 3, Srm", _STREET, lat=59.6, lon=17.9),
    {"taxon": {"id": CROW}, "event": {"startDate": "2026-06-14T07:00:00+02:00"},
     "location": {"decimalLatitude": 59.5, "decimalLongitude": 17.8}},  # no site
]}


class _FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self.ok = True
        self._body = body
        self.text = "ok"
        self.content = b"body"

    def json(self):
        return self._body


class _RoutingSession:
    """Answers by endpoint, so the planner can make as many calls as it likes."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(url)
        if url.endswith("/Observations/TaxonAggregation"):
            return _FakeResponse(_TAXON_AGG)
        if url.endswith("/Observations/Search"):
            return _FakeResponse(_SEARCH)
        if url.endswith("/taxa"):
            want = set((json or {}).get("taxonIds") or [])
            return _FakeResponse([t for t in _TAXA if t["taxonId"] in want])
        raise AssertionError(f"unexpected URL {url}")


class _MultiSiteSession:
    """A different named site per latitude band of the Sthlm->Uppsala route, so
    dedup / edge-buffer behaviour can be exercised."""

    _BANDS = [
        (59.40, "Startnära", 59.35, 18.03),
        (59.52, "Mitten A", 59.47, 17.95),
        (59.66, "Mitten B", 59.60, 17.82),
        (99.0, "Slutnära", 59.82, 17.68),
    ]

    def __init__(self):
        self.calls = []

    def _site_for(self, lat):
        for hi, name, slat, slon in self._BANDS:
            if lat < hi:
                return name, slat, slon
        return self._BANDS[-1][1:]

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(url)
        if url.endswith("/Observations/TaxonAggregation"):
            return _FakeResponse(_TAXON_AGG)
        if url.endswith("/taxa"):
            want = set((json or {}).get("taxonIds") or [])
            return _FakeResponse([t for t in _TAXA if t["taxonId"] in want])
        if url.endswith("/Observations/Search"):
            lat = json["geographics"]["geometries"][0]["coordinates"][1]
            name, slat, slon = self._site_for(lat)
            sid = f"urn:lsid:artportalen.se:site:{name}"
            taxa = [WARBLER, CURLEW, LAPWING, HERON, SWAN, MALLARD, TIT, CROW]
            recs = [_rec(t, 13 - i % 5, f"{name}, Srm", sid, lat=slat, lon=slon)
                    for i, t in enumerate(taxa)]
            return _FakeResponse({"totalCount": len(recs), "records": recs})
        raise AssertionError(f"unexpected URL {url}")


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
class SuggestRestStopsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _run(self, **kwargs):
        session = _RoutingSession()
        self.enterContext(_patch(adb, "_session", lambda: session))
        kwargs.setdefault("significance_of", _significance_of)
        stops = route_planner.suggest_rest_stops(
            ROUTE, 2_000, today=TODAY, **kwargs
        )
        return stops, session

    def test_returns_ranked_stops_with_shape(self):
        stops, _ = self._run(num_stops=5)
        self.assertGreaterEqual(len(stops), 1)
        self.assertLessEqual(len(stops), 5)
        self.assertEqual([s["rank"] for s in stops], list(range(1, len(stops) + 1)))
        first = stops[0]
        for key in ("score", "breakdown", "location", "locality", "location_id",
                    "municipality", "county", "species_count", "highlights",
                    "notable_recent", "top_species", "distance_along_route_m",
                    "detour_m"):
            self.assertIn(key, first)
        self.assertEqual(first["location"]["type"], "Point")
        self.assertEqual(len(first["location"]["coordinates"]), 2)
        self.assertEqual(first["locality"], "Fågelsjön")
        self.assertEqual(first["location_id"], _SITE)

    def test_highlights_explain_why_the_stop_is_worthwhile(self):
        stops, _ = self._run()
        highlights = stops[0]["highlights"]
        self.assertTrue(highlights)
        warbler = next(h for h in highlights if h["taxon_id"] == WARBLER)
        self.assertIn("red-listed", warbler["reason"])
        self.assertNotIn(CROW, [h["taxon_id"] for h in highlights])

    def test_notable_recent_lists_the_red_listed_sighting(self):
        stops, _ = self._run()
        names = [n["scientific_name"] for n in stops[0]["notable_recent"]]
        self.assertIn("Acrocephalus paludicola", names)

    def test_stop_is_a_named_site_not_a_thin_locality(self):
        stops, _ = self._run()
        # "Villagatan 3" has only 2 taxa - below the site bar - so it loses to
        # "Fågelsjön" every time.
        self.assertEqual(stops[0]["locality"], "Fågelsjön")
        self.assertNotIn("Villagatan", [s["locality"] for s in stops])
        # the site coordinate is the mean of its records, not a route point
        lon, lat = stops[0]["location"]["coordinates"]
        self.assertAlmostEqual(lon, 17.8, places=3)
        self.assertAlmostEqual(lat, 59.5, places=3)

    def test_call_budget_is_bounded(self):
        stops, session = self._run(num_stops=5)
        # one aggregation per sample point + one search per winner + a taxa batch.
        self.assertLess(len(session.calls), 120)
        self.assertGreater(len(session.calls), len(stops))

    def test_identical_hotspots_are_deduplicated(self):
        # Every sample point returns the same records -> the same best site, so
        # the planner must collapse the winners onto one stop.
        stops, _ = self._run(num_stops=5)
        self.assertEqual(len(stops), 1)

    def _run_multisite(self, **kwargs):
        session = _MultiSiteSession()
        self.enterContext(_patch(adb, "_session", lambda: session))
        kwargs.setdefault("significance_of", _significance_of)
        return route_planner.suggest_rest_stops(ROUTE, 2_000, today=TODAY, **kwargs)

    def test_stops_near_the_route_ends_are_excluded(self):
        stops = self._run_multisite(num_stops=5, edge_buffer_m=9_000, min_gap_m=1_000)
        names = {s["locality"] for s in stops}
        self.assertNotIn("Startnära", names)
        self.assertNotIn("Slutnära", names)
        self.assertTrue(names)  # the middle sites survive

    def test_stops_respect_minimum_spacing(self):
        stops = self._run_multisite(num_stops=5, edge_buffer_m=500, min_gap_m=25_000)
        alongs = sorted(s["distance_along_route_m"] for s in stops)
        for a, b in zip(alongs, alongs[1:]):
            self.assertGreaterEqual(b - a, 25_000)

    def test_redlist_code_parses_the_swedish_phrase(self):
        self.assertEqual(route_planner._redlist_code("Sårbar (VU)"), "VU")
        self.assertEqual(route_planner._redlist_code("Nationellt utdöd (RE)"), "RE")
        self.assertEqual(route_planner._redlist_code("EN"), "EN")
        self.assertEqual(route_planner._redlist_code("Livskraftig (LC)"), "")
        self.assertEqual(route_planner._redlist_code(None), "")

    def test_rejects_degenerate_geometry(self):
        with self.assertRaises(ValueError):
            route_planner.suggest_rest_stops(
                {"type": "LineString", "coordinates": [[18.0, 59.0]]},
                1_000, today=TODAY,
            )
