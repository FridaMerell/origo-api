"""Refresh cached Species rows from Dyntaxa and Artfakta.

    python manage.py resync_species                 # every species not synced in 30 days
    python manage.py resync_species --older-than 7   # ... not synced in 7 days
    python manage.py resync_species --all            # every species
    python manage.py resync_species --taxon 101664 --taxon 206040
    python manage.py resync_species --missing biotopes    # only where biotopes is empty
    python manage.py resync_species --dry-run

Each species is refreshed in its own transaction (``upsert_species`` is atomic),
so one failure never rolls back the others. Artfakta data - species
information, landskapstyper and biotoper - is best-effort inside
``upsert_species`` and its absence never blocks a refresh.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from tempus.models import Species
from tempus.services import artdatabanken

# JSON list fields on Species that upsert_species fills from Artfakta.
MISSING_FIELDS = ("biotopes", "landscape_types")


class Command(BaseCommand):
    help = "Re-pull cached Species from Dyntaxa + Artfakta and bump synced_at."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=artdatabanken.RESYNC_STALE_AFTER_DAYS,
            metavar="DAYS",
            help=(
                "Only resync species whose synced_at is older than DAYS "
                f"(default {artdatabanken.RESYNC_STALE_AFTER_DAYS}); species "
                "never synced are always included. Ignored with --all or --taxon."
            ),
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Resync every species regardless of synced_at.",
        )
        parser.add_argument(
            "--taxon",
            action="append",
            type=int,
            default=[],
            metavar="DYNTAXA_ID",
            help="Resync only this dyntaxa_taxon_id (repeatable).",
        )
        parser.add_argument(
            "--missing",
            action="append",
            default=[],
            choices=MISSING_FIELDS,
            metavar="FIELD",
            help=(
                "Resync species whose FIELD is empty - use to backfill a newly "
                f"added Artfakta field. One of {', '.join(MISSING_FIELDS)} "
                "(repeatable). Overrides the staleness selection."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the species that would be resynced and exit.",
        )

    def handle(self, *args, **options):
        queryset = self._select(options)
        total = queryset.count()
        if not total:
            self.stdout.write("Nothing to resync.")
            return

        self.stdout.write(f"{total} species to resync.")
        if options["dry_run"]:
            for species in queryset:
                self.stdout.write(
                    f"  would resync {species.dyntaxa_taxon_id} {species}"
                )
            return

        succeeded = failed = 0
        try:
            for taxon_id, species, error in artdatabanken.resync_species_batch(queryset):
                if error is None:
                    succeeded += 1
                    self.stdout.write(f"  synced {taxon_id} {species}")
                else:
                    failed += 1
                    self.stderr.write(f"  {taxon_id}: {error}")
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Done: {succeeded} synced, {failed} failed.")
        )

    def _select(self, options):
        queryset = Species.objects.order_by("scientific_name")
        if options["taxon"]:
            return queryset.filter(dyntaxa_taxon_id__in=options["taxon"])
        if options["missing"]:
            condition = Q()
            for field in options["missing"]:
                condition |= Q(**{field: []}) | Q(**{f"{field}__isnull": True})
            return queryset.filter(condition)
        if options["all"]:
            return queryset
        return artdatabanken.stale_species(older_than_days=options["older_than"])
