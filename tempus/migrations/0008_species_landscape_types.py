from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tempus', '0007_phenogram'),
    ]

    operations = [
        migrations.AddField(
            model_name='species',
            name='landscape_types',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
