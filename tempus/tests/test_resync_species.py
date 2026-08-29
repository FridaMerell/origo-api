import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tempus.models import Species
from tempus.services import artdatabanken


class _patch:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


class ResyncSpeciesCommandTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.fresh = Species.objects.create(
            dyntaxa_taxon_id=1, scientific_name="Fresh one", synced_at=now
        )
        self.stale = Species.objects.create(
            dyntaxa_taxon_id=2,
            scientific_name="Stale one",
            synced_at=now - datetime.timedelta(days=60),
        )
        self.never = Species.objects.create(
            dyntaxa_taxon_id=3, scientific_name="Never synced"
        )

    def _run(self, *args):
        calls = []
        out = StringIO()
        with _patch(artdatabanken, "upsert_species", lambda tid: calls.append(tid)):
            call_command("resync_species", *args, stdout=out, stderr=out)
        return calls, out.getvalue()

    def test_default_picks_stale_and_never_synced(self):
        calls, _ = self._run()
        self.assertEqual(sorted(calls), [2, 3])

    def test_older_than_1000_leaves_only_never_synced(self):
        calls, _ = self._run("--older-than", "1000")
        self.assertEqual(sorted(calls), [3])  # 60-day-old row is not that stale

    def test_all_takes_everything(self):
        calls, _ = self._run("--all")
        self.assertEqual(sorted(calls), [1, 2, 3])

    def test_taxon_filter_is_explicit(self):
        calls, _ = self._run("--taxon", "1")
        self.assertEqual(calls, [1])

    def test_missing_biotopes_backfills_regardless_of_synced_at(self):
        # self.fresh (taxon 1) was synced "now" but has no biotopes.
        self.stale.biotopes = [{"id": 9, "code": "S", "name": "Skog", "significance": "har"}]
        self.stale.save(update_fields=["biotopes"])
        calls, _ = self._run("--missing", "biotopes")
        self.assertEqual(sorted(calls), [1, 3])  # fresh + never; stale has biotopes

    def test_dry_run_calls_nothing(self):
        calls, out = self._run("--dry-run")
        self.assertEqual(calls, [])
        self.assertIn("would resync", out)

    def test_api_error_is_reported_and_skipped(self):
        def boom(tid):
            if tid == 2:
                raise artdatabanken.ArtdatabankenAPIError("POST", "/taxa", 502, "nope")

        out = StringIO()
        with _patch(artdatabanken, "upsert_species", boom):
            call_command("resync_species", "--all", stdout=out, stderr=out)
        self.assertIn("1 failed", out.getvalue())
