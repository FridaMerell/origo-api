from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

from accounts.models import User
from flux.models import Project, Task


class TaskRecurrenceDateTests(SimpleTestCase):
    def test_next_monthly_due_date_clamps_to_last_day_of_month(self):
        task = Task(
            title='Pay invoices',
            due_date=date(2026, 1, 31),
            recurrence=Task.Recurrence.MONTHLY,
        )

        self.assertEqual(task.next_recurrence_due_date(), date(2026, 2, 28))

    def test_next_recurrence_respects_end_date(self):
        task = Task(
            title='Weekly report',
            due_date=date(2026, 8, 30),
            recurrence=Task.Recurrence.WEEKLY,
            recurrence_end_date=date(2026, 9, 5),
        )

        self.assertIsNone(task.next_recurrence_due_date())


class TaskRecurrenceCreationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida')
        self.project = Project.objects.create(name='Flux')
        self.project.members.add(self.user)

    def test_create_next_recurrence_copies_task_details(self):
        task = Task.objects.create(
            project=self.project,
            title='Review plan',
            description='Read the weekly project plan.',
            due_date=date(2026, 8, 30),
            recurrence=Task.Recurrence.WEEKLY,
            recurrence_interval=2,
            priority=Task.Priority.HIGH,
            status=Task.Status.DONE,
            files=[{'name': 'plan.pdf'}],
        )
        task.assignees.add(self.user)

        next_task = task.create_next_recurrence()

        self.assertEqual(next_task.project, task.project)
        self.assertEqual(next_task.title, task.title)
        self.assertEqual(next_task.description, task.description)
        self.assertEqual(next_task.due_date, date(2026, 9, 13))
        self.assertEqual(next_task.recurrence, Task.Recurrence.WEEKLY)
        self.assertEqual(next_task.recurrence_interval, 2)
        self.assertEqual(next_task.recurrence_source, task)
        self.assertEqual(next_task.priority, Task.Priority.HIGH)
        self.assertEqual(next_task.status, Task.Status.NOT_STARTED)
        self.assertEqual(next_task.files, [{'name': 'plan.pdf'}])
        self.assertEqual(list(next_task.assignees.all()), [self.user])

    def test_finishing_recurring_task_enqueues_reschedule_after_commit(self):
        task = Task.objects.create(
            project=self.project,
            title='Weekly review',
            due_date=date(2026, 8, 30),
            recurrence=Task.Recurrence.WEEKLY,
        )

        with mock.patch('flux.tasks.create_next_recurring_task.enqueue') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                task.status = Task.Status.DONE
                task.save()

        enqueue.assert_called_once_with(str(task.pk))
