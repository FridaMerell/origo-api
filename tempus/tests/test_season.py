import datetime
import types

from django.test import SimpleTestCase

from tempus.services import season


def _phenogram(start, end, peak_start=None, peak_end=None):
    """Just the four envelope fields season.status_for reads."""
    return types.SimpleNamespace(
        start_day_of_year=start,
        end_day_of_year=end,
        peak_start_day=peak_start,
        peak_end_day=peak_end,
    )


class StatusForTests(SimpleTestCase):
    TODAY = datetime.date(2026, 6, 1)  # day 152

    def test_reads_the_envelope(self):
        pg = _phenogram(121, 213, 152, 175)
        result = season.status_for(pg, today=self.TODAY)
        self.assertEqual(result["status"], "at_peak")
        self.assertTrue(result["is_in_season"])

    def test_out_of_season(self):
        pg = _phenogram(1, 40)
        result = season.status_for(pg, today=self.TODAY)
        self.assertEqual(result["status"], "out_of_season")


class MatchesStatusTests(SimpleTestCase):
    TODAY = datetime.date(2026, 6, 1)

    def test_boolean_names_overlap(self):
        pg = _phenogram(121, 213, 152, 175)  # at peak on TODAY
        self.assertTrue(season.matches_status(pg, "in_season", today=self.TODAY))
        self.assertTrue(season.matches_status(pg, "at_peak", today=self.TODAY))
        self.assertFalse(season.matches_status(pg, "coming_into_season", today=self.TODAY))

    def test_exact_status_name(self):
        # Day 140: inside the window but before the peak sub-window.
        pg = _phenogram(121, 213, 152, 175)
        may20 = datetime.date(2026, 5, 20)
        self.assertEqual(season.status_for(pg, today=may20)["status"], "in_season")
        self.assertTrue(season.matches_status(pg, "in_season", today=may20))
        self.assertFalse(season.matches_status(pg, "at_peak", today=may20))

    def test_valid_status(self):
        self.assertTrue(season.valid_status("in_season"))
        self.assertTrue(season.valid_status("out_of_season"))
        self.assertTrue(season.valid_status("coming_into_season"))
        self.assertFalse(season.valid_status("whenever"))


class FilterByStatusTests(SimpleTestCase):
    TODAY = datetime.date(2026, 6, 1)

    def test_keeps_only_matching_rows(self):
        rows = [
            _phenogram(121, 213, 152, 175),  # at peak / in season
            _phenogram(1, 40),               # out of season
            _phenogram(160, 250),            # coming into season (starts day 160)
        ]
        in_season = season.filter_by_status(rows, "in_season", today=self.TODAY)
        self.assertEqual(in_season, [rows[0]])
        coming = season.filter_by_status(rows, "coming_into_season", today=self.TODAY)
        self.assertEqual(coming, [rows[2]])
