# Generated manually for recurring Flux tasks.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('flux', '0005_milestone_files_project_files_task_files_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='recurrence',
            field=models.CharField(
                choices=[
                    ('none', 'None'),
                    ('daily', 'Daily'),
                    ('weekly', 'Weekly'),
                    ('monthly', 'Monthly'),
                    ('yearly', 'Yearly'),
                ],
                default='none',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_interval',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_source',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='recurrence_occurrences',
                to='flux.task',
            ),
        ),
    ]
