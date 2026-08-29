"""Unit tests for scripts/phenology.py -- stdlib only.

    python -m unittest discover -s tests        # from the skill root
    python tests/test_phenology.py              # or run this file directly
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import phenology as ph  # noqa: E402


def _rec(date, lat=59.0, lon=17.0, taxon=1):
    return {"taxon": {"id": taxon}, "event": {"startDate": date},
            "location": {"decimalLatitude": lat, "decimalLongitude": lon}}


class Parsing(unittest.TestCase):
    def test_to_date_accepts_str_date_datetime_timestamp(self):
        self.assertEqual(ph.to_date("2024-06-14"), dt.date(2024, 6, 14))
        self.assertEqual(ph.to_date("2024-06-14T09:30:00Z"), dt.date(2024, 6, 14))
        self.assertEqual(ph.to_date(dt.date(2024, 6, 14)), dt.date(2024, 6, 14))
        self.assertEqual(ph.to_date(dt.datetime(2024, 6, 14, 9, 30)), dt.date(2024, 6, 14))

    def test_iso_week_folds_53_into_52(self):
        self.assertEqual(ph.iso_week("2020-12-31"), 52)  # 2020 has an ISO week 53
        self.assertEqual(ph.iso_week("2024-01-01"), 1)

    def test_sos_record_dates_handles_missing_and_bad(self):
        recs = [
            {"event": {"startDate": "2024-05-01"}},
            {"event": {}},                       # missing
            {"event": {"startDate": "not-a-date"}},  # unparseable
            {},                                  # missing branch
        ]
        self.assertEqual(ph.sos_record_dates(recs), [dt.date(2024, 5, 1)])


class Phenogram(unittest.TestCase):
    def test_all_52_weeks_present_and_counts(self):
        h = ph.phenogram(["2024-01-03", "2024-01-04", "2024-07-01"])
        self.assertEqual(set(h), set(range(1, 53)))
        self.assertEqual(h[1], 2.0)
        self.assertEqual(sum(h.values()), 3.0)

    def test_weights_sum_quantity(self):
        h = ph.phenogram(["2024-07-01", "2024-07-02"], weights=[10, None])
        self.assertEqual(sum(h.values()), 10.0)

    def test_normalize_sums_to_one(self):
        h = ph.normalize(ph.phenogram(["2024-01-03", "2024-07-01", "2024-07-02"]))
        self.assertAlmostEqual(sum(h.values()), 1.0)

    def test_smooth_is_circular_and_conserves_mass(self):
        h = ph.phenogram(["2024-01-01"])          # week 1 only
        s = ph.smooth(h, 1)
        self.assertGreater(s[52], 0)              # bleeds across the year boundary
        self.assertAlmostEqual(sum(s.values()), sum(h.values()))

    def test_divide_effort_correction(self):
        taxon = {w: 0.0 for w in ph.WEEKS}; taxon[20] = 5.0; taxon[21] = 5.0
        effort = {w: 0.0 for w in ph.WEEKS}; effort[20] = 100.0  # wk21 effort unknown
        d = ph.divide(taxon, effort)
        self.assertAlmostEqual(d[20], 0.05)
        self.assertEqual(d[21], 0.0)              # no effort data -> 0, not div-by-zero


class Decluster(unittest.TestCase):
    def test_mob_on_one_spot_one_week_collapses_to_one(self):
        mob = [_rec("2024-06-10") for _ in range(300)]
        self.assertEqual(len(list(ph.decluster(mob))), 1)

    def test_distinct_sites_kept(self):
        recs = [_rec("2024-06-10", lat=59.0, lon=17.0),
                _rec("2024-06-10", lat=58.0, lon=16.0)]
        self.assertEqual(len(list(ph.decluster(recs))), 2)

    def test_long_stay_keeps_one_per_week(self):
        recs = ([_rec("2024-06-10")] * 5 + [_rec("2024-06-17")] * 5
                + [_rec("2024-06-24")] * 5)
        weeks = {ph.iso_week(d) for d in ph.decluster(recs)}
        self.assertEqual(len(weeks), 3)

    def test_missing_coords_pass_through_missing_date_dropped(self):
        recs = [
            {"taxon": {"id": 1}, "event": {"startDate": "2024-06-10"}, "location": {}},
            {"taxon": {"id": 1}, "event": {}, "location": {"decimalLatitude": 59.0,
                                                           "decimalLongitude": 17.0}},
        ]
        out = list(ph.decluster(recs))
        self.assertEqual(out, [dt.date(2024, 6, 10)])


class Curve(unittest.TestCase):
    def setUp(self):
        # adults weeks ~18-26, peak 22
        dates = []
        for yr in range(2016, 2024):
            for wk in range(18, 27):
                dates += [dt.date.fromisocalendar(yr, wk, 3)] * (10 - abs(22 - wk))
        self.h = ph.smooth(ph.phenogram(dates), 1)

    def test_peak_and_window(self):
        self.assertEqual(ph.peak_week(self.h), 22)
        lo, hi = ph.activity_window(self.h)
        self.assertTrue(17 <= lo <= 20 and 24 <= hi <= 28, (lo, hi))

    def test_window_handles_year_straddling_season(self):
        winter = ([dt.date.fromisocalendar(y, w, 3)
                   for y in range(2018, 2024) for w in (50, 51, 52, 1, 2)])
        lo, hi = ph.activity_window(ph.phenogram(winter))
        self.assertIn(lo, (49, 50, 51))
        self.assertIn(hi, (1, 2, 3))

    def test_limb(self):
        self.assertEqual(ph.limb(self.h, 19), "ascending")
        self.assertEqual(ph.limb(self.h, 25), "descending")
        self.assertEqual(ph.limb(self.h, 40), "off")


class Scoring(unittest.TestCase):
    def setUp(self):
        self.base = {w: 0.0 for w in ph.WEEKS}
        for w in range(18, 27):
            self.base[w] = 10 - abs(22 - w)

    def test_zero_outside_season(self):
        self.assertEqual(ph.in_season_score(self.base, 40), 0.0)

    def test_unseen_scores_higher_than_long_ago_seen(self):
        wk = 20
        unseen = ph.in_season_score(self.base, wk, weeks_of_data=8)
        old = ph.in_season_score(self.base, wk, weeks_of_data=8,
                                 reported_this_year=True, first_week_this_year=14)
        self.assertGreater(unseen, old)

    def test_ascending_beats_descending(self):
        up = ph.in_season_score(self.base, 19, weeks_of_data=8)
        down = ph.in_season_score(self.base, 25, weeks_of_data=8)
        self.assertGreater(up, down)

    def test_confidence_scales_with_years(self):
        thin = ph.in_season_score(self.base, 20, weeks_of_data=1)
        thick = ph.in_season_score(self.base, 20, weeks_of_data=10)
        self.assertGreater(thick, thin)


class Status(unittest.TestCase):
    W = (20, 30)

    def test_all_states(self):
        self.assertEqual(ph.season_status(self.W, 15, reported_this_year=False),
                         "not_yet_due")
        self.assertEqual(ph.season_status(self.W, 25, reported_this_year=False),
                         "due_now_unseen")
        self.assertEqual(ph.season_status(self.W, 25, reported_this_year=True,
                                          first_week_this_year=24), "just_started")
        self.assertEqual(ph.season_status(self.W, 29, reported_this_year=True,
                                          first_week_this_year=21), "seen")
        self.assertEqual(ph.season_status(self.W, 33, reported_this_year=False),
                         "overdue")
        self.assertEqual(ph.season_status(self.W, 45, reported_this_year=False),
                         "season_over")


if __name__ == "__main__":
    unittest.main()
