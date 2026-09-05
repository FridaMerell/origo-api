"""Every user-owned Tempus resource must be scoped to its owner.

Routes, checklists and observations are all private per-user data (unlike
the shared reference data covered elsewhere) -- these tests exist because
nothing previously asserted that a second user can't see or touch them.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from tempus.models import Checklist, ChecklistItem, Observation, Route, RouteStop, Species

User = get_user_model()


class RouteOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='x')
        self.stranger = User.objects.create_user(username='stranger', password='x')
        self.route = Route.objects.create(
            user=self.owner, name='Morning walk', planned_date='2026-06-01',
            geometry={'type': 'LineString', 'coordinates': [[18.0, 59.0], [18.1, 59.1]]},
            corridor_metres=500,
        )

    def test_owner_can_see_their_route(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.get('/api/tempus/routes/')

        ids = [row['id'] for row in response.data]
        self.assertIn(str(self.route.pk), ids)

    def test_stranger_cannot_see_the_route(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get('/api/tempus/routes/')

        self.assertEqual(response.data, [])

    def test_stranger_cannot_fetch_the_route_by_id(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get(f'/api/tempus/routes/{self.route.pk}/')

        self.assertEqual(response.status_code, 404)

    def test_creating_a_route_sets_the_owner_from_the_request(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.post(
            '/api/tempus/routes/',
            {
                'name': 'New route', 'planned_date': '2026-07-01', 'corridor_metres': 200,
                'geometry': {'type': 'LineString', 'coordinates': [[18.0, 59.0], [18.1, 59.1]]},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user'], self.stranger.pk)

    def test_cannot_add_a_stop_to_someone_elses_route(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.post(
            '/api/tempus/route-stops/',
            {
                'route': self.route.pk, 'sequence': 1, 'name': 'Rest stop',
                'location': {'type': 'Point', 'coordinates': [18.05, 59.05]},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_stranger_cannot_see_the_routes_stops(self):
        RouteStop.objects.create(
            route=self.route, sequence=1, name='Rest stop',
            location={'type': 'Point', 'coordinates': [18.05, 59.05]},
        )
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get('/api/tempus/route-stops/')

        self.assertEqual(response.data, [])


class ChecklistOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='x')
        self.stranger = User.objects.create_user(username='stranger', password='x')
        self.species = Species.objects.create(
            dyntaxa_taxon_id=1, scientific_name='Turdus merula', swedish_name='Koltrast'
        )
        self.checklist = Checklist.objects.create(user=self.owner, name='Summer trip')
        self.item = ChecklistItem.objects.create(checklist=self.checklist, species=self.species, sequence=1)

    def test_stranger_cannot_see_the_checklist(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get('/api/tempus/checklists/')

        self.assertEqual(response.data, [])

    def test_stranger_cannot_add_an_item_to_someone_elses_checklist(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.post(
            '/api/tempus/checklist-items/',
            {'checklist': self.checklist.pk, 'species': str(self.species.pk), 'sequence': 2},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_stranger_cannot_see_the_checklists_items(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get('/api/tempus/checklist-items/')

        self.assertEqual(response.data, [])


class ObservationOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='x')
        self.stranger = User.objects.create_user(username='stranger', password='x')
        self.species = Species.objects.create(
            dyntaxa_taxon_id=1, scientific_name='Turdus merula', swedish_name='Koltrast'
        )
        self.observation = Observation.objects.create(
            user=self.owner, species=self.species, observed_at='2026-06-01T08:00:00Z',
            location={'type': 'Point', 'coordinates': [18.0, 59.0]},
        )

    def test_stranger_cannot_see_the_observation(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.get('/api/tempus/observations/')

        self.assertEqual(response.data, [])

    def test_creating_an_observation_sets_the_owner_from_the_request(self):
        client = APIClient()
        client.force_authenticate(user=self.stranger)

        response = client.post(
            '/api/tempus/observations/',
            {
                'species': str(self.species.pk), 'observed_at': '2026-06-02T08:00:00Z',
                'location': {'type': 'Point', 'coordinates': [18.0, 59.0]},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user'], self.stranger.pk)
