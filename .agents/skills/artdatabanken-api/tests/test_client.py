"""Unit tests for scripts/artdatabanken_client.py -- no network.

A fake requests.Session is injected, so these check URL/header/param assembly,
error handling and the paging/normalisation logic without hitting the API.

    python -m unittest discover -s tests
    python tests/test_client.py
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# The client does `import requests` lazily in __init__. Tests replace the session
# with a fake immediately, so a stub module is enough when requests isn't
# installed. If the real package is present, this leaves it untouched.
if "requests" not in sys.modules:
    try:
        import requests  # noqa: F401
    except ImportError:
        _stub = types.ModuleType("requests")
        _stub.Session = lambda: types.SimpleNamespace(headers={},
                                                      mount=lambda *a, **k: None)
        _adapters = types.ModuleType("requests.adapters")
        _adapters.HTTPAdapter = lambda *a, **k: None
        _stub.adapters = _adapters
        sys.modules["requests"] = _stub
        sys.modules["requests.adapters"] = _adapters

from artdatabanken_client import (  # noqa: E402
    ArtdatabankenClient, ArtdatabankenError, ArtportalenWriteClient,
    ArtportalenAccessError,
)


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.ok = 200 <= status < 300
        self.text = text or ("" if body is None else str(body))
        self.content = b"" if body is None else b"body"

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self._responses = list(responses)
        self.calls = []

    def mount(self, *a, **k):
        pass

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(dict(method=method, url=url, params=params,
                               json=json, headers=headers or {}))
        return self._responses.pop(0)


def make_client(responses, **kw):
    c = ArtdatabankenClient(sos_key="SOSKEY", taxon_key="TAXKEY", **kw)
    c._session = FakeSession(responses)
    return c


class RequestAssembly(unittest.TestCase):
    def test_builds_url_and_sends_subscription_key(self):
        c = make_client([FakeResp(200, {"ok": 1})])
        c.data_providers()
        call = c._session.calls[0]
        self.assertEqual(
            call["url"],
            "https://api.artdatabanken.se/species-observation-system/v1/DataProviders",
        )
        self.assertEqual(call["headers"]["Ocp-Apim-Subscription-Key"], "SOSKEY")
        self.assertNotIn("Authorization", call["headers"])

    def test_missing_key_raises_before_any_http(self):
        c = make_client([])
        c._keys["artfakta"] = None
        with self.assertRaises(ArtdatabankenError):
            c.species_information(101664)
        self.assertEqual(c._session.calls, [])

    def test_non_2xx_raises_with_status_and_body(self):
        c = make_client([FakeResp(429, text="rate limited")])
        with self.assertRaises(ArtdatabankenError) as cm:
            c.data_providers()
        self.assertEqual(cm.exception.status, 429)
        self.assertIn("rate limited", cm.exception.body)

    def test_204_returns_none(self):
        c = make_client([FakeResp(204)])
        self.assertIsNone(c.data_providers())

    def test_protected_without_token_provider_raises(self):
        c = make_client([])
        with self.assertRaises(ArtdatabankenError):
            c.search_observations({}, protected=True)

    def test_protected_adds_bearer_from_provider(self):
        c = make_client([FakeResp(200, {"totalCount": 0, "records": []})],
                        oauth_token_provider=lambda: "TOK")
        c.search_observations({}, protected=True)
        self.assertEqual(c._session.calls[0]["headers"]["Authorization"], "Bearer TOK")


class Observations(unittest.TestCase):
    def test_take_and_window_validation(self):
        c = make_client([])
        with self.assertRaises(ValueError):
            c.search_observations({}, take=5000)
        with self.assertRaises(ValueError):
            c.search_observations({}, skip=9900, take=500)
        self.assertEqual(c._session.calls, [])

    def test_search_passes_body_and_paging_params(self):
        c = make_client([FakeResp(200, {"totalCount": 1, "records": [{"a": 1}]})])
        flt = {"taxon": {"ids": [1]}}
        out = c.search_observations(flt, skip=10, take=20, sort_by="event.startDate")
        call = c._session.calls[0]
        self.assertEqual(call["json"], flt)
        self.assertEqual(call["params"]["skip"], 10)
        self.assertEqual(call["params"]["take"], 20)
        self.assertEqual(call["params"]["sortBy"], "event.startDate")
        self.assertEqual(out["totalCount"], 1)

    def test_iter_observations_pages_then_stops(self):
        c = make_client([
            FakeResp(200, {"totalCount": 3, "records": [{"i": 1}, {"i": 2}]}),
            FakeResp(200, {"totalCount": 3, "records": [{"i": 3}]}),
        ])
        got = list(c.iter_observations({"x": 1}, page_size=2))
        self.assertEqual([r["i"] for r in got], [1, 2, 3])
        self.assertEqual(len(c._session.calls), 2)

    def test_iter_observations_stops_on_empty_page(self):
        c = make_client([FakeResp(200, {"totalCount": 999, "records": []})])
        self.assertEqual(list(c.iter_observations({}, page_size=10)), [])

    def test_count_handles_count_totalcount_and_bare_int(self):
        self.assertEqual(make_client([FakeResp(200, {"count": 7})])
                         .count_observations({}), 7)
        self.assertEqual(make_client([FakeResp(200, {"totalCount": 9})])
                         .count_observations({}), 9)
        self.assertEqual(make_client([FakeResp(200, 5)]).count_observations({}), 5)


class Taxonomy(unittest.TestCase):
    def test_find_taxon_ids_from_list_response(self):
        c = make_client([FakeResp(200, [{"taxonId": 101664}, {"id": 5}, {"taxonId": 101664}])])
        self.assertEqual(c.find_taxon_ids("aurorafjäril"), [101664, 5])

    def test_find_taxon_ids_from_wrapped_response(self):
        c = make_client([FakeResp(200, {"data": [{"acceptedTaxonId": 42}]})])
        self.assertEqual(c.find_taxon_ids("x"), [42])

    def test_taxon_service_uses_taxon_base_and_key(self):
        c = make_client([FakeResp(200, {"taxonId": 1})])
        c.get_taxon(1)
        call = c._session.calls[0]
        self.assertEqual(call["url"],
                         "https://api.artdatabanken.se/taxonservice/v1/taxa/1")
        self.assertEqual(call["headers"]["Ocp-Apim-Subscription-Key"], "TAXKEY")


class WriteStub(unittest.TestCase):
    def test_unconfigured_write_client_refuses(self):
        w = ArtportalenWriteClient()
        self.assertFalse(w.is_configured)
        with self.assertRaises(ArtportalenAccessError):
            w.report_sighting({"taxonId": 1})

    def test_configured_flag_needs_all_three(self):
        w = ArtportalenWriteClient(write_key="k", base_url="https://x",
                                   oauth_token_provider=lambda: "t")
        self.assertTrue(w.is_configured)


if __name__ == "__main__":
    unittest.main()
