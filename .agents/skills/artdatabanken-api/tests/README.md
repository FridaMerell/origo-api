# Tests

Stdlib `unittest`, no third-party dependencies.

```bash
cd ..                                   # skill root
python -m unittest discover -s tests    # or: python -m unittest discover -s tests -v
```

- **test_phenology.py** — the pure phenology helpers: parsing, phenogram build,
  `decluster()` (twitcher pile-ons, long stays, missing data), curve reading
  (`activity_window`, `peak_week`, `limb`, including a year-straddling season),
  `in_season_score`, and every `season_status` state.
- **test_client.py** — `ArtdatabankenClient` request assembly (URL, subscription
  key, bearer token), error handling, the SOS take/window guards, paging in
  `iter_observations`, response-shape normalisation in `find_taxon_ids`, and the
  write-client access guard. A fake `requests.Session` is injected; a stub
  `requests` module is registered only if the real one isn't installed.

When you port the scripts into Tempus, copy the relevant cases into the project's
own test suite and run them there too (with real `requests` present).
