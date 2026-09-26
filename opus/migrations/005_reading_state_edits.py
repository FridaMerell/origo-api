from django.db import migrations, models
import django.db.models.deletion


def migrate_reading_progress(apps, schema_editor):
    ReadingProgress = apps.get_model("opus", "ReadingProgress")

    rows = (
        ReadingProgress.objects
        .select_related("version__work", "unit")
        .order_by("user_id", "version__work_id", "-updated_at", "-id")
    )

    seen = set()

    for row in rows:
        key = (row.user_id, row.version.work_id)

        if key in seen:
            row.delete()
            continue

        seen.add(key)
        row.work_id = row.version.work_id
        row.position = row.unit.position
        row.character_index = row.offset
        row.save(
            update_fields=[
                "work",
                "position",
                "character_index",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("opus", "0004_author_remove_work_author_bibliographyentry_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="readingprogress",
            name="work",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reading_progress",
                to="opus.work",
            ),
        ),
        migrations.AddField(
            model_name="readingprogress",
            name="position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="readingprogress",
            name="character_index",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
            ),
        ),
        migrations.RunPython(
            migrate_reading_progress,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="readingprogress",
            name="work",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reading_progress",
                to="opus.work",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="readingprogress",
            name="opus_reading_progress_per_user_version",
        ),
        migrations.RemoveField(
            model_name="readingprogress",
            name="version",
        ),
        migrations.RemoveField(
            model_name="readingprogress",
            name="unit",
        ),
        migrations.RemoveField(
            model_name="readingprogress",
            name="offset",
        ),
        migrations.AddConstraint(
            model_name="readingprogress",
            constraint=models.UniqueConstraint(
                fields=("user", "work"),
                name="opus_reading_progress_per_user_work",
            ),
        ),
    ]