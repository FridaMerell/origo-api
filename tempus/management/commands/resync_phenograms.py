"""Rebuild stored phenograms by enqueueing background build tasks.

    python manage.py resync_phenograms                  # species with a stale or missing curve
    python manage.py resync_phenograms --older-than 30   # ... curve older than 30 days
    python manage.py resync_phenograms --all             # every species
    python manage.py resync_phenograms --taxon 101664 --taxon 206040
    python manage.py resync_phenograms --no-refresh      # skip species that already have every curve
    python manage.py resync_phenograms --dry-run

Mirrors ``resync_species`` but for the seasonal activity curves. One
``tempus.tasks.fan_out_species_phenograms`` task is queued per selected species;
each then queues one ``generate_phenogram`` build per ``GeoArea`` (plus the
whole-range row). A worker must be running to do the work
(``python manage.py db_worker``).
"""

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone
import datetime

from tempus.models import Phenogram, Species
from tempus import tasks

# A phenogram older than this is treated as stale (matches PhenogramSerializer).
STALE_AFTER_DAYS = 90


class Command(BaseCommand):
    help = "Enqueue phenogram rebuilds for stale/missing curves - for cron / shell."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=STALE_AFTER_DAYS,
            metavar="DAYS",
            help=(
                "Select species with a phenogram whose computed_at is older than "
                f"DAYS (default {STALE_AFTER_DAYS}); species with no phenogram at "
                "all are always included. Ignored with --all or --taxon."
            ),
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Rebuild phenograms for every species regardless of age.",
        )
        parser.add_argument(
            "--taxon",
            action="append",
            type=int,
            default=[],
            metavar="DYNTAXA_ID",
            help="Rebuild only this dyntaxa_taxon_id (repeatable).",
        )
        parser.add_argument(
            "--no-refresh",
            action="store_true",
            help="Only build curves that are missing; leave existing rows untouched.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the species that would be queued and exit.",
        )

    def handle(self, *args, **options):
        queryset = self._select(options)
        total = queryset.count()
        if not total:
            self.stdout.write("Nothing to resync.")
            return

        refresh = not options["no_refresh"]
        self.stdout.write(f"{total} species to resync (refresh={refresh}).")
        if options["dry_run"]:
            for species in queryset:
                self.stdout.write(
                    f"  would queue {species.dyntaxa_taxon_id} {species}"
                )
            return

        for species_pk in queryset.values_list("pk", flat=True):
            tasks.fan_out_species_phenograms.enqueue(species_pk, refresh=refresh)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: queued {total} fan-out task(s). "
                "Run a worker (python manage.py db_worker) to build them."
            )
        )

    def _select(self, options):
        queryset = Species.objects.order_by("scientific_name")
        if options["taxon"]:
            return queryset.filter(dyntaxa_taxon_id__in=options["taxon"])
        if options["all"]:
            return queryset

        cutoff = timezone.now() - datetime.timedelta(
            days=max(0, options["older_than"])
        )
        has_any = Phenogram.objects.filter(species=OuterRef("pk"))
        has_stale = has_any.filter(computed_at__lt=cutoff)
        return queryset.filter(Exists(has_stale) | ~Exists(has_any))
