from datetime import date

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Project, Task

User = get_user_model()


class TaskViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Origo')
        self.project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_task(self):
        response = self.client.post('/api/flux/tasks/', {'project': self.project.pk, 'title': 'Ship it'})

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_create_a_task(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/flux/tasks/', {'project': self.project.pk, 'title': 'Ship it'})

        self.assertEqual(response.status_code, 400)

    def test_assignee_must_be_a_project_member(self):
        response = self.client.post(
            '/api/flux/tasks/',
            {'project': self.project.pk, 'title': 'Ship it', 'assignees': [self.outsider.pk]},
        )

        self.assertEqual(response.status_code, 400)

    def test_recurring_task_requires_a_due_date(self):
        response = self.client.post(
            '/api/flux/tasks/',
            {'project': self.project.pk, 'title': 'Ship it', 'recurrence': Task.Recurrence.WEEKLY},
        )

        self.assertEqual(response.status_code, 400)

    def test_recurrence_end_date_cannot_precede_the_due_date(self):
        response = self.client.post(
            '/api/flux/tasks/',
            {
                'project': self.project.pk, 'title': 'Ship it',
                'recurrence': Task.Recurrence.WEEKLY, 'due_date': date(2026, 6, 1),
                'recurrence_end_date': date(2026, 5, 1),
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_parent_task_cannot_create_a_cycle(self):
        parent = Task.objects.create(project=self.project, title='Parent')
        child = Task.objects.create(project=self.project, title='Child', parent=parent)

        response = self.client.patch(f'/api/flux/tasks/{parent.pk}/', {'parent': child.pk})

        self.assertEqual(response.status_code, 400)

    def test_task_cannot_require_itself(self):
        task = Task.objects.create(project=self.project, title='Task')

        response = self.client.patch(f'/api/flux/tasks/{task.pk}/', {'requirements': [task.pk]})

        self.assertEqual(response.status_code, 400)

    def test_circular_requirement_is_rejected(self):
        a = Task.objects.create(project=self.project, title='A')
        b = Task.objects.create(project=self.project, title='B')
        a.requirements.add(b)

        response = self.client.patch(f'/api/flux/tasks/{b.pk}/', {'requirements': [a.pk]})

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_task(self):
        Task.objects.create(project=self.project, title='Ship it')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/flux/tasks/')

        self.assertEqual(response.data, [])
