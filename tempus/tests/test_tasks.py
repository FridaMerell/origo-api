"""Async phenogram generation.

These exercise the task functions with the *immediate* django-tasks backend, so
``enqueue`` runs the work inline. Requires ``django-tasks`` to be installed.
"""

from django.test import TestCase, override_settings

from tempus import tasks
from tempus.models import GeoArea, Phenogram, Species

IMMEDIATE = {"default": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"}}

SWEDEN = {
    "type": "MultiPolygon",
    "coordinates": [[[[11.0, 55.0], [24.0, 55.0], [24.0, 69.0], [11.0, 69.0], [11.0, 55.0]]]],
}


class _patch:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


@override_settings(TASKS=IMMEDIATE)
class GeneratePhenogramTaskTests(TestCase):
    def setUp(self):
        self.species = Species.objects.create(
            dyntaxa_taxon_id=101664, scientific_name="Anthocharis cardamines"
        )
        self.area = GeoArea.objects.create(
            name="Sverige", kind=GeoArea.Kind.COUNTRY, country_code="SE", geometry=SWEDEN
        )

    def test_unit_task_calls_get_phenogram(self):
        seen = []
        with _patch(tasks.phenogram, "get_phenogram",
                    lambda sp, area, **kw: seen.append((sp.pk, getattr(area, "pk", None), kw))):
            tasks.generate_phenogram.enqueue(self.species.pk, self.area.pk)
        self.assertEqual(seen, [(self.species.pk, self.area.pk, {"refresh": True})])

    def test_unit_task_missing_species_is_a_no_op(self):
        called = []
        with _patch(tasks.phenogram, "get_phenogram", lambda *a, **k: called.append(1)):
            tasks.generate_phenogram.enqueue(999999, self.area.pk)
        self.assertEqual(called, [])

    def test_unit_task_swallows_artdatabanken_errors(self):
        def boom(*a, **k):
            raise tasks.artdatabanken.ArtdatabankenAPIError("GET", "/x", 502, "down")

        with _patch(tasks.phenogram, "get_phenogram", boom):
            tasks.generate_phenogram.enqueue(self.species.pk, self.area.pk)  # no raise

    def test_fan_out_species_enqueues_one_per_area(self):
        GeoArea.objects.create(
            name="Skåne", kind=GeoArea.Kind.PROVINCE, country_code="SE", geometry=SWEDEN
        )
        enqueued = []
        with _patch(tasks.generate_phenogram, "enqueue",
                    lambda *a, **k: enqueued.append((a, k))):
            tasks.fan_out_species_phenograms.enqueue(self.species.pk)
        self.assertEqual(len(enqueued), 2)
        self.assertEqual({args[1] for args, _ in enqueued},
                         set(GeoArea.objects.values_list("pk", flat=True)))

    def test_fan_out_area_enqueues_one_per_species(self):
        Species.objects.create(dyntaxa_taxon_id=222, scientific_name="Pieris napi")
        enqueued = []
        with _patch(tasks.generate_phenogram, "enqueue",
                    lambda *a, **k: enqueued.append(a)):
            tasks.fan_out_area_phenograms.enqueue(self.area.pk)
        self.assertEqual(len(enqueued), 2)


@override_settings(TASKS=IMMEDIATE)
class PhenogramSignalTests(TestCase):
    def test_species_create_fans_out(self):
        calls = []
        with _patch(tasks.fan_out_species_phenograms, "enqueue",
                    lambda pk, **k: calls.append(pk)):
            with self.captureOnCommitCallbacks(execute=True):
                species = Species.objects.create(
                    dyntaxa_taxon_id=1, scientific_name="X"
                )
        self.assertEqual(calls, [species.pk])

    def test_geoarea_create_fans_out(self):
        calls = []
        with _patch(tasks.fan_out_area_phenograms, "enqueue",
                    lambda pk, **k: calls.append(pk)):
            with self.captureOnCommitCallbacks(execute=True):
                area = GeoArea.objects.create(
                    name="A", kind=GeoArea.Kind.COUNTY, country_code="SE", geometry=SWEDEN
                )
        self.assertEqual(calls, [area.pk])
