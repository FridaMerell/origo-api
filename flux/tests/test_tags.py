from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Project, Tag

User = get_user_model()


class TagViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.other = User.objects.create_user(username='other', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_creating_a_tag_sets_the_creator(self):
        response = self.client.post('/api/flux/tags/', {'name': 'urgent'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Tag.objects.get().created_by, self.member)

    def test_own_tag_can_be_edited(self):
        tag = Tag.objects.create(name='urgent', created_by=self.member)

        response = self.client.patch(f'/api/flux/tags/{tag.pk}/', {'color': '#ff0000'})

        self.assertEqual(response.status_code, 200)

    def test_other_users_tag_cannot_be_edited(self):
        tag = Tag.objects.create(name='urgent', created_by=self.other)

        response = self.client.patch(f'/api/flux/tags/{tag.pk}/', {'color': '#ff0000'})

        self.assertEqual(response.status_code, 404)

    def test_a_tag_visible_on_a_shared_project_is_listed_but_not_editable(self):
        tag = Tag.objects.create(name='urgent', created_by=self.other)
        project = Project.objects.create(name='Origo')
        project.members.add(self.member)
        project.tags.add(tag)

        list_response = self.client.get('/api/flux/tags/')
        edit_response = self.client.patch(f'/api/flux/tags/{tag.pk}/', {'color': '#ff0000'})

        self.assertIn(tag.pk, [row['id'] for row in list_response.data])
        self.assertEqual(edit_response.status_code, 404)
