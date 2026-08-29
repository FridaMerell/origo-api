import django.core.validators
import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tempus', '0006_remove_checklistsighting_tempus_unique_checklist_sighting_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Phenogram',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('years', models.PositiveSmallIntegerField(default=8)),
                ('weeks', models.JSONField(default=list)),
                ('peak_week', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(52)])),
                ('window_start_week', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(52)])),
                ('window_end_week', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(52)])),
                ('start_day_of_year', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(366)])),
                ('peak_start_day', models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(366)])),
                ('peak_end_day', models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(366)])),
                ('end_day_of_year', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(366)])),
                ('confidence', models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)])),
                ('smooth_weeks', models.PositiveSmallIntegerField(default=1)),
                ('declustered', models.BooleanField(default=True)),
                ('record_count', models.PositiveIntegerField(default=0)),
                ('record_limit_hit', models.BooleanField(default=False)),
                ('sample_count', models.PositiveIntegerField(default=0)),
                ('years_present', models.PositiveSmallIntegerField(default=0)),
                ('date_from', models.DateField()),
                ('date_to', models.DateField()),
                ('computed_at', models.DateTimeField()),
                ('geo_area', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='phenograms', to='tempus.geoarea')),
                ('species', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='phenograms', to='tempus.species')),
            ],
            options={
                'ordering': ('-computed_at',),
            },
        ),
        migrations.AddIndex(
            model_name='phenogram',
            index=models.Index(fields=['species', 'geo_area'], name='tempus_phenogram_sp_area_idx'),
        ),
        migrations.AddConstraint(
            model_name='phenogram',
            constraint=models.UniqueConstraint(condition=models.Q(('geo_area__isnull', False)), fields=('species', 'geo_area', 'years'), name='tempus_unique_phenogram_area'),
        ),
        migrations.AddConstraint(
            model_name='phenogram',
            constraint=models.UniqueConstraint(condition=models.Q(('geo_area__isnull', True)), fields=('species', 'years'), name='tempus_unique_phenogram_range'),
        ),
    ]
