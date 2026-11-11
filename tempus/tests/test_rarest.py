import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tempus.models import GeoArea, Observation, Phenogram, Species
from tempus.services.year_summary import rarest


def _square(lon, lat):
    return {
        "type": "MultiPolygon",
        "coordinates": [[[[lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat + 1], [lon, lat]]]],
    }


def _point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


class RarestTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="observer", password="x")
        self.south = GeoArea.objects.create(
            name="Södermanland", kind=GeoArea.Kind.PROVINCE, country_code="SE", geometry=_square(16, 58)
        )
        self.north = GeoArea.objects.create(
            name="Lappland", kind=GeoArea.Kind.PROVINCE, country_code="SE", geometry=_square(18, 66)
        )
        self.bluethroat = Species.objects.create(
            dyntaxa_taxon_id=1, scientific_name="Luscinia svecica", swedish_name="blåhake", significance=0.2
        )
        self.tit = Species.objects.create(
            dyntaxa_taxon_id=2, scientific_name="Poecile palustris", swedish_name="entita", significance=0.3
        )
        self._area_value(self.bluethroat, self.south, 0.8)
        self._area_value(self.bluethroat, self.north, 0.1)

    def _area_value(self, species, area, value, *, basis=None):
        Phenogram.objects.create(
            species=species, geo_area=area, peak_week=22, window_start_week=18, window_end_week=26,
            start_day_of_year=120, end_day_of_year=180, significance=value,
            significance_basis={"group": 4000104} if basis is None else basis,
            date_from=datetime.date(2019, 1, 1), date_to=datetime.date(2026, 6, 1), computed_at=timezone.now(),
        )

    def _observe(self, species, location):
        Observation.objects.create(user=self.user, species=species, observed_at=timezone.now(), location=location)

    def _rows(self):
        return [
            {"id": str(species.pk), "significance": species.significance, "red_list_category": ""}
            for species in (self.bluethroat, self.tit)
        ]

    def _rarest(self):
        return rarest(Observation.objects.filter(user=self.user), self._rows())

    def test_species_in_a_province_where_it_is_seldom_found_is_rarest(self):
        self._observe(self.bluethroat, _point(16.5, 58.5))
        self._observe(self.tit, _point(16.5, 58.5))
        result = self._rarest()
        self.assertEqual(result["id"], str(self.bluethroat.pk))
        self.assertEqual(result["significance"], 0.8)

    def test_same_species_where_it_is_common_is_not(self):
        self._observe(self.bluethroat, _point(18.5, 66.5))
        self._observe(self.tit, _point(16.5, 58.5))
        self.assertEqual(self._rarest()["id"], str(self.tit.pk))

    def test_whole_country_value_counts_outside_rated_provinces(self):
        self._observe(self.bluethroat, _point(12.5, 56.5))
        self._observe(self.tit, _point(16.5, 58.5))
        # 0.2 for the bluethroat outside both provinces, 0.3 for the tit
        self.assertEqual(self._rarest()["id"], str(self.tit.pk))

    def test_observation_without_position_counts_with_the_whole_country_value(self):
        self._observe(self.bluethroat, {})
        result = self._rarest()
        self.assertEqual(result["id"], str(self.bluethroat.pk))
        self.assertEqual(result["significance"], 0.2)

    def test_values_from_before_the_species_group_measure_are_ignored(self):
        Phenogram.objects.filter(species=self.bluethroat, geo_area=self.north).update(
            significance=0.95, significance_basis={"species_cells": 1, "area_cells": 40}
        )
        self._observe(self.bluethroat, _point(18.5, 66.5))
        self._observe(self.tit, _point(16.5, 58.5))
        self.assertEqual(self._rarest()["id"], str(self.tit.pk))

    def test_nothing_rated_is_none(self):
        self.bluethroat.significance = None
        self.tit.significance = None
        Phenogram.objects.all().delete()
        self._observe(self.tit, _point(16.5, 58.5))
        self.assertIsNone(self._rarest())
