from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apsis.models import Post

User = get_user_model()


class PostViewSetTests(APITestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='author', password='x')
        self.other = User.objects.create_user(username='other', password='x')
        self.staff = User.objects.create_user(username='staff', password='x', is_staff=True)

    def test_anonymous_can_list_posts(self):
        Post.objects.create(content='hello')
        client = APIClient()

        response = client.get('/api/apsis/posts/')

        self.assertEqual(response.status_code, 200)

    def test_anonymous_cannot_create_a_post(self):
        client = APIClient()

        response = client.post('/api/apsis/posts/', {'content': 'hello'})

        self.assertEqual(response.status_code, 401)

    def test_authenticated_user_can_create_a_post(self):
        client = APIClient()
        client.force_authenticate(user=self.author)

        response = client.post('/api/apsis/posts/', {'content': 'hello'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.get().author, self.author)

    def test_author_field_is_set_from_the_request_not_the_payload(self):
        client = APIClient()
        client.force_authenticate(user=self.author)

        client.post('/api/apsis/posts/', {'content': 'hello', 'author': self.other.pk})

        self.assertEqual(Post.objects.get().author, self.author)

    def test_author_can_edit_their_own_post(self):
        post = Post.objects.create(content='original', author=self.author)
        client = APIClient()
        client.force_authenticate(user=self.author)

        response = client.patch(f'/api/apsis/posts/{post.pk}/', {'content': 'edited'})

        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertEqual(post.content, 'edited')

    def test_other_user_cannot_edit_the_post(self):
        post = Post.objects.create(content='original', author=self.author)
        client = APIClient()
        client.force_authenticate(user=self.other)

        response = client.patch(f'/api/apsis/posts/{post.pk}/', {'content': 'edited'})

        self.assertEqual(response.status_code, 403)
        post.refresh_from_db()
        self.assertEqual(post.content, 'original')

    def test_staff_can_edit_any_post(self):
        post = Post.objects.create(content='original', author=self.author)
        client = APIClient()
        client.force_authenticate(user=self.staff)

        response = client.patch(f'/api/apsis/posts/{post.pk}/', {'content': 'edited'})

        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_delete_the_post(self):
        post = Post.objects.create(content='original', author=self.author)
        client = APIClient()
        client.force_authenticate(user=self.other)

        response = client.delete(f'/api/apsis/posts/{post.pk}/')

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

    def test_str_falls_back_to_placeholder_when_a_file_entry_has_no_name(self):
        post = Post(files=[{'size': 100}])

        self.assertEqual(str(post), '?')

    def test_str_reports_no_files_when_empty(self):
        post = Post(files=[])

        self.assertEqual(str(post), 'No files')
