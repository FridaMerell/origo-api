import datetime

from django.test import SimpleTestCase

from tempus.services import phenology as ph


def _record(date, lat=59.0, lon=17.0, taxon=1):
    return {
        "taxon": {"id": taxon},
        "event": {"startDate": date},
        "location": {"decimalLatitude": lat, "decimalLongitude": lon},
    }


class ParsingTests(SimpleTestCase):
    def test_to_date_accepts_several_shapes(self):
        self.assertEqual(ph.to_date("2024-06-14"), datetime.date(2024, 6, 14))
        self.assertEqual(ph.to_date("2024-06-14T09:30:00Z"), datetime.date(2024, 6, 14))
        self.assertEqual(ph.to_date(datetime.datetime(2024, 6, 14, 9, 30)),
                         datetime.date(2024, 6, 14))

    def test_iso_week_folds_53(self):
        self.assertEqual(ph.iso_week("2020-12-31"), 52)
        self.assertEqual(ph.iso_week("2024-01-01"), 1)

    def test_observation_dates_skips_missing_and_bad(self):
        records = [
            {"event": {"startDate": "2024-05-01"}},
            {"event": {}},
            {"event": {"startDate": "nope"}},
            {},
        ]
        self.assertEqual(ph.observation_dates(records), [datetime.date(2024, 5, 1)])


class PhenogramTests(SimpleTestCase):
    def test_all_weeks_present(self):
        hist = ph.phenogram(["2024-01-03", "2024-07-01"])
        self.assertEqual(set(hist), set(range(1, 53)))
        self.assertEqual(sum(hist.values()), 2.0)

    def test_weights_sum_quantity(self):
        hist = ph.phenogram(["2024-07-01", "2024-07-02"], weights=[10, None])
        self.assertEqual(sum(hist.values()), 10.0)

    def test_normalize_and_smooth(self):
        hist = ph.phenogram(["2024-01-01"])
        self.assertAlmostEqual(sum(ph.normalize(hist).values()), 1.0)
        smoothed = ph.smooth(hist, 1)
        self.assertGreater(smoothed[52], 0.0)  # circular
        self.assertAlmostEqual(sum(smoothed.values()), sum(hist.values()))

    def test_divide_handles_zero_effort(self):
        taxon = {w: 0.0 for w in ph.WEEKS}
        taxon[20] = 4.0
        effort = {w: 0.0 for w in ph.WEEKS}
        effort[20] = 100.0
        result = ph.divide(taxon, effort)
        self.assertAlmostEqual(result[20], 0.04)
        self.assertEqual(result[21], 0.0)


class DeclusterTests(SimpleTestCase):
    def test_mob_collapses_to_one(self):
        mob = [_record("2024-06-10") for _ in range(200)]
        self.assertEqual(len(list(ph.decluster(mob))), 1)

    def test_distinct_sites_kept(self):
        records = [_record("2024-06-10", lat=59.0, lon=17.0),
                   _record("2024-06-10", lat=58.0, lon=16.0)]
        self.assertEqual(len(list(ph.decluster(records))), 2)

    def test_long_stay_one_per_week(self):
        records = [_record("2024-06-10")] * 5 + [_record("2024-06-17")] * 5
        weeks = {ph.iso_week(d) for d in ph.decluster(records)}
        self.assertEqual(len(weeks), 2)


class CurveTests(SimpleTestCase):
    def setUp(self):
        dates = []
        for year in range(2016, 2024):
            for week in range(18, 27):
                dates += [datetime.date.fromisocalendar(year, week, 3)] * (10 - abs(22 - week))
        self.hist = ph.smooth(ph.phenogram(dates), 1)

    def test_peak_and_window(self):
        self.assertEqual(ph.peak_week(self.hist), 22)
        lo, hi = ph.activity_window(self.hist)
        self.assertLessEqual(lo, 20)
        self.assertGreaterEqual(hi, 24)

    def test_limb(self):
        self.assertEqual(ph.limb(self.hist, 19), "ascending")
        self.assertEqual(ph.limb(self.hist, 25), "descending")
        self.assertEqual(ph.limb(self.hist, 40), "off")

    def test_season_window_days_shape(self):
        window = ph.season_window_days(self.hist, years_present=8)
        self.assertLess(window["start_day_of_year"], window["peak_start_day"])
        self.assertLessEqual(window["peak_start_day"], window["peak_end_day"])
        self.assertLessEqual(window["peak_end_day"], window["end_day_of_year"])
        self.assertTrue(1 <= window["start_day_of_year"] <= 366)
        self.assertEqual(window["confidence"], 1.0)


class ScoreAndStatusTests(SimpleTestCase):
    def setUp(self):
        self.base = {w: 0.0 for w in ph.WEEKS}
        for week in range(18, 27):
            self.base[week] = 10 - abs(22 - week)

    def test_score_zero_out_of_season(self):
        self.assertEqual(ph.in_season_score(self.base, 40), 0.0)

    def test_unseen_beats_long_ago(self):
        unseen = ph.in_season_score(self.base, 20, years_present=8)
        old = ph.in_season_score(self.base, 20, years_present=8,
                                 reported_this_year=True, first_week_this_year=14)
        self.assertGreater(unseen, old)

    def test_status_states(self):
        window = (20, 30)
        self.assertEqual(ph.season_status(window, 15, reported_this_year=False),
                         "not_yet_due")
        self.assertEqual(ph.season_status(window, 25, reported_this_year=False),
                         "due_now_unseen")
        self.assertEqual(ph.season_status(window, 25, reported_this_year=True,
                                          first_week_this_year=24), "just_started")
        self.assertEqual(ph.season_status(window, 29, reported_this_year=True,
                                          first_week_this_year=21), "seen")
        self.assertEqual(ph.season_status(window, 33, reported_this_year=False),
                         "overdue")
        self.assertEqual(ph.season_status(window, 46, reported_this_year=False),
                         "season_over")


class PhenogramStatusTests(SimpleTestCase):
    # Spring window: days 121..213, peak 152..175.
    ENVELOPE = {
        "start_day_of_year": 121,
        "peak_start_day": 152,
        "peak_end_day": 175,
        "end_day_of_year": 213,
    }

    def _status(self, doy, **kwargs):
        return ph.phenogram_status(self.ENVELOPE, doy, **kwargs)

    def test_out_of_season(self):
        result = self._status(20)
        self.assertEqual(result["status"], "out_of_season")
        self.assertFalse(result["is_in_season"])
        self.assertFalse(result["is_coming_into_season"])
        self.assertEqual(result["days_until_start"], 101)
        self.assertEqual(result["days_until_end"], 0)

    def test_coming_into_season(self):
        result = self._status(110, soon_days=21)
        self.assertEqual(result["status"], "coming_into_season")
        self.assertTrue(result["is_coming_into_season"])
        self.assertEqual(result["days_until_start"], 11)

    def test_in_season_before_peak(self):
        result = self._status(140)
        self.assertEqual(result["status"], "in_season")
        self.assertTrue(result["is_in_season"])
        self.assertFalse(result["at_peak"])

    def test_at_peak(self):
        result = self._status(160)
        self.assertEqual(result["status"], "at_peak")
        self.assertTrue(result["at_peak"])
        self.assertTrue(result["is_in_season"])

    def test_going_out_of_season(self):
        result = self._status(205, last_chance_days=14)
        self.assertEqual(result["status"], "going_out_of_season")
        self.assertTrue(result["is_in_season"])
        self.assertTrue(result["is_going_out_of_season"])
        self.assertEqual(result["days_until_end"], 8)

    def test_window_wraps_new_year(self):
        wrapped = {"start_day_of_year": 340, "end_day_of_year": 40}
        self.assertTrue(ph.phenogram_status(wrapped, 5)["is_in_season"])
        self.assertTrue(ph.phenogram_status(wrapped, 350)["is_in_season"])
        self.assertFalse(ph.phenogram_status(wrapped, 100)["is_in_season"])
