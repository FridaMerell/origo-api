"""Regression tests for PhenogramViewSet's list()/get_queryset() split.

``?status=`` can't be a plain SQL WHERE (the day-of-year window may wrap the
year boundary), so it's matched in Python. The view used to run that Python
pass, then re-query the database by the matched pks to get something the
generic view machinery could serialize/paginate/filter further -- fetching
the same rows twice. list() now serializes the already-hydrated matches
directly; get_queryset() (which also backs retrieve()) still takes the
pk__in round trip, deliberately, since a single-row lookup there is cheap and
changing its semantics wasn't asked for. These tests pin both halves down.
"""
import datetime

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from tempus.models import GeoArea, Phenogram, Species

User = get_user_model()


def _today_day_of_year():
    return datetime.date.today().timetuple().tm_yday


class PhenogramViewSetStatusFilterTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='birder', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.geo_area = GeoArea.objects.create(name='Sweden', kind=GeoArea.Kind.COUNTRY, country_code='SE')
        self.in_season_species = Species.objects.create(
            dyntaxa_taxon_id=1, scientific_name='Turdus merula', swedish_name='Koltrast'
        )
        self.out_of_season_species = Species.objects.create(
            dyntaxa_taxon_id=2, scientific_name='Anser anser', swedish_name='Gragas'
        )

        today = _today_day_of_year()
        in_start, in_end = max(1, today - 5), min(366, today + 5)
        # A fixed window guaranteed to sit on the other side of the year from
        # "today", however the test happens to be scheduled.
        out_start, out_end = (200, 210) if today <= 183 else (10, 20)

        now = timezone.now()
        self.in_season = Phenogram.objects.create(
            species=self.in_season_species, geo_area=self.geo_area,
            peak_week=1, window_start_week=1, window_end_week=52,
            start_day_of_year=in_start, end_day_of_year=in_end,
            date_from=now.date(), date_to=now.date(), computed_at=now,
        )
        self.out_of_season = Phenogram.objects.create(
            species=self.out_of_season_species, geo_area=self.geo_area,
            peak_week=1, window_start_week=1, window_end_week=52,
            start_day_of_year=out_start, end_day_of_year=out_end,
            date_from=now.date(), date_to=now.date(), computed_at=now,
        )

    def test_status_filter_returns_only_matching_rows(self):
        response = self.client.get('/api/tempus/phenograms/', {'status': 'in_season'})

        ids = {row['id'] for row in response.data}
        self.assertIn(str(self.in_season.pk), ids)
        self.assertNotIn(str(self.out_of_season.pk), ids)

    def test_status_filter_combines_with_species_param(self):
        # The species filter should narrow the set the Python status pass
        # looks at, not just be applied on top of it afterwards.
        response = self.client.get(
            '/api/tempus/phenograms/',
            {'status': 'in_season', 'species': self.out_of_season_species.pk},
        )

        self.assertEqual(response.data, [])

    def test_unknown_status_is_rejected(self):
        response = self.client.get('/api/tempus/phenograms/', {'status': 'nonsense'})

        self.assertEqual(response.status_code, 400)

    def test_no_status_param_returns_everything(self):
        response = self.client.get('/api/tempus/phenograms/')

        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {str(self.in_season.pk), str(self.out_of_season.pk)})

    def test_retrieve_still_applies_the_status_filter(self):
        """get_queryset() (unlike list()) was deliberately left as-is."""
        response = self.client.get(
            f'/api/tempus/phenograms/{self.out_of_season.pk}/', {'status': 'in_season'}
        )

        self.assertEqual(response.status_code, 404)

    def test_retrieve_succeeds_when_the_status_matches(self):
        response = self.client.get(
            f'/api/tempus/phenograms/{self.in_season.pk}/', {'status': 'in_season'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], str(self.in_season.pk))
