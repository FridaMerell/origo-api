import datetime

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

ROUTE = {
    "type": "LineString",
    "coordinates": [[18.0649, 59.3293], [17.6389, 59.8586]],  # Sthlm -> Uppsala
}

_TAXON_AGG = {"records": [
    {"taxon": {"id": CROW, "scientificName": "Corvus cornix",
               "vernacularName": "kråka"}, "count": 900},
    {"taxon": {"id": MALLARD, "scientificName": "Anas platyrhynchos",
               "vernacularName": "gräsand"}, "count": 300},
    {"taxon": {"id": TIT, "scientificName": "Parus major",
               "vernacularName": "talgoxe"}, "count": 200},
    {"taxon": {"id": WARBLER, "scientificName": "Acrocephalus paludicola",
               "vernacularName": "vattensångare",
               "redListCategory": "EN"}, "count": 2},
]}

_GRID = {"gridCells": [
    {"boundingBox": [17.90, 59.40, 17.92, 59.42], "observationsCount": 120},
    {"boundingBox": [17.80, 59.50, 17.82, 59.52], "observationsCount": 40},
]}

_SEARCH = {"totalCount": 3, "records": [
    {"taxon": {"id": WARBLER, "scientificName": "Acrocephalus paludicola",
               "vernacularName": "vattensångare", "redListCategory": "EN"},
     "event": {"startDate": "2026-06-13"},
     "location": {"locality": "Angarnssjöängen", "county": "Stockholm"}},
    {"taxon": {"id": CROW, "scientificName": "Corvus cornix"},
     "event": {"startDate": "2026-06-14"},
     "location": {"locality": "Angarnssjöängen", "county": "Stockholm"}},
    {"taxon": {"id": TIT, "scientificName": "Parus major"},
     "event": {"startDate": "2026-06-10"},
     "location": {"locality": "Angarnssjöängen", "county": "Stockholm"}},
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
        if url.endswith("/Observations/GeoGridAggregation"):
            return _FakeResponse(_GRID)
        if url.endswith("/Observations/Search"):
            return _FakeResponse(_SEARCH)
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
    def _run(self, **kwargs):
        session = _RoutingSession()
        self.enterContext(_patch(adb, "_session", lambda: session))
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
        for key in ("score", "breakdown", "location", "locality", "county",
                    "species_count", "highlights", "notable_recent",
                    "top_species", "distance_along_route_m", "detour_m"):
            self.assertIn(key, first)
        self.assertEqual(first["location"]["type"], "Point")
        self.assertEqual(len(first["location"]["coordinates"]), 2)

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

    def test_locality_is_resolved_from_recent_records(self):
        stops, _ = self._run()
        self.assertEqual(stops[0]["locality"], "Angarnssjöängen")

    def test_call_budget_is_bounded(self):
        stops, session = self._run(num_stops=5)
        # 1 corridor + one per sample point + 2 per localised winner.
        self.assertLess(len(session.calls), 120)
        self.assertGreater(len(session.calls), len(stops))

    def test_identical_hotspots_are_deduplicated(self):
        # Every sample point returns the same aggregation, so the planner must
        # collapse the winners that snap to the same cell.
        stops, _ = self._run(num_stops=5)
        self.assertEqual(len(stops), 1)

    def test_rejects_degenerate_geometry(self):
        with self.assertRaises(ValueError):
            route_planner.suggest_rest_stops(
                {"type": "LineString", "coordinates": [[18.0, 59.0]]},
                1_000, today=TODAY,
            )
