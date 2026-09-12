"""Every user-owned Tempus resource must be scoped to its owner.

Routes, checklists and observations are all private per-user data (unlike
the shared reference data covered elsewhere) -- these tests exist because
nothing previously asserted that a second user can't see or touch them.
"""
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from tempus.models import Checklist, ChecklistItem, Locale, Observation, Route, RouteStop, Species
from tempus.services.checklists import sync_observations_to_checklists

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

    def test_observation_response_includes_species_detail(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.get(f'/api/tempus/observations/{self.observation.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['species_detail'],
            {'dyntaxa_taxon_id': 1, 'swedish_name': 'Koltrast'},
        )
        self.assertEqual(
            response.data['species_detail'],
            {'dyntaxa_taxon_id': 1, 'swedish_name': 'Koltrast'},
        )
        self.assertEqual(
            response.data['species_detail'],
            {'dyntaxa_taxon_id': 1, 'swedish_name': 'Koltrast'},
        )

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

    def test_observation_response_includes_species_detail(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.get(f'/api/tempus/observations/{self.observation.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['species_detail'],
            {'dyntaxa_taxon_id': 1, 'swedish_name': 'Koltrast'},
        )


LOCALE_SQUARE = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[17.0, 59.0], [18.0, 59.0], [18.0, 60.0], [17.0, 60.0], [17.0, 59.0]]]
    ],
}


class LocaleOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="locale-owner", password="x")
        self.other_user = User.objects.create_user(username="other-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.locale = Locale.objects.create(
            user=self.owner,
            name="Home",
            geometry=LOCALE_SQUARE,
        )

    def test_create_ignores_a_submitted_owner(self):
        response = self.client.post(
            "/api/tempus/locales/",
            {"name": "Garden", "geometry": LOCALE_SQUARE, "user": self.other_user.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["user"], self.owner.pk)

    def test_update_cannot_transfer_locale_to_another_user(self):
        response = self.client.patch(
            f"/api/tempus/locales/{self.locale.pk}/",
            {"user": self.other_user.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.locale.refresh_from_db()
        self.assertEqual(self.locale.user, self.owner)


class LocaleObservationTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="observation-owner", password="x")
        self.other_user = User.objects.create_user(username="other-locale-owner", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.species = Species.objects.create(
            dyntaxa_taxon_id=999,
            scientific_name="Turdus merula",
            swedish_name="Koltrast",
        )
        self.owner_locale = Locale.objects.create(
            user=self.owner,
            name="Home",
            geometry=LOCALE_SQUARE,
        )
        self.other_locale = Locale.objects.create(
            user=self.other_user,
            name="Elsewhere",
            geometry=LOCALE_SQUARE,
        )
        self.observation = Observation.objects.create(
            user=self.owner,
            species=self.species,
            observed_at=datetime(2026, 9, 12, 10, tzinfo=timezone.utc),
            location={"type": "Point", "coordinates": [17.5, 59.5]},
            locale=self.owner_locale,
        )

    def test_update_cannot_assign_another_users_locale(self):
        response = self.client.patch(
            f"/api/tempus/observations/{self.observation.pk}/",
            {"locale": self.other_locale.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.observation.refresh_from_db()
        self.assertEqual(self.observation.locale, self.owner_locale)

    def test_new_observation_is_assigned_to_the_owners_matching_locale(self):
        response = self.client.post(
            "/api/tempus/observations/",
            {
                "species": str(self.species.pk),
                "observed_at": "2026-09-12T10:00:00Z",
                "location": {"type": "Point", "coordinates": [17.5, 59.5]},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["locale"], self.owner_locale.pk)

    def test_explicit_checklist_observation_keeps_its_locale_classification(self):
        checklist = Checklist.objects.create(user=self.owner, name="Garden birds")
        item = ChecklistItem.objects.create(
            checklist=checklist,
            species=self.species,
            sequence=1,
        )

        response = self.client.post(
            "/api/tempus/observations/",
            {
                "species": str(self.species.pk),
                "checklist_items": [str(item.pk)],
                "observed_at": "2026-09-12T10:00:00Z",
                "location": {"type": "Point", "coordinates": [17.5, 59.5]},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["locale"], self.owner_locale.pk)

    def test_checklist_cannot_reference_another_users_locale(self):
        response = self.client.post(
            "/api/tempus/checklists/",
            {
                "name": "Garden birds",
                "species": [str(self.species.pk)],
                "locale": self.other_locale.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("locale", response.data)

    def test_sync_links_an_existing_observation_inside_the_checklist_locale(self):
        checklist = Checklist.objects.create(
            user=self.owner,
            name="Garden birds",
            locale=self.owner_locale,
        )
        item = ChecklistItem.objects.create(
            checklist=checklist,
            species=self.species,
            sequence=1,
        )
        self.observation.checklist_items.clear()

        observations_linked, links_created = sync_observations_to_checklists(
            user=self.owner,
            checklist=checklist,
        )

        self.assertEqual((observations_linked, links_created), (1, 1))
        self.assertTrue(self.observation.checklist_items.filter(pk=item.pk).exists())
