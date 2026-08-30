"""Generate temporary BirdNET detections for local development.

Examples:
    python manage.py fake_birdnet_detections --device pi-birdnet-001
    python manage.py fake_birdnet_detections --device pi-birdnet-001 --count 100 --hours 6
    python manage.py fake_birdnet_detections --device pi-birdnet-001 --species "Turdus merula" --seed 42
    python manage.py fake_birdnet_detections --device pi-birdnet-001 --count 20 --interval 1
"""

import random
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tempus.models import BirdnetDetection, BirdnetDevice, Species


class Command(BaseCommand):
    help = "Generate fake BirdNET detections for an existing device."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            required=True,
            metavar="IDENTIFIER",
            help="Identifier of the BirdnetDevice that receives the detections.",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=25,
            metavar="N",
            help="Number of detections to create (default: 25, maximum: 10000).",
        )
        parser.add_argument(
            "--hours",
            type=float,
            default=24.0,
            metavar="HOURS",
            help="Spread timestamps across the previous HOURS (default: 24).",
        )
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.5,
            metavar="VALUE",
            help="Lowest generated confidence, between 0 and 1 (default: 0.5).",
        )
        parser.add_argument(
            "--max-confidence",
            type=float,
            default=0.99,
            metavar="VALUE",
            help="Highest generated confidence, between 0 and 1 (default: 0.99).",
        )
        parser.add_argument(
            "--species",
            action="append",
            default=[],
            metavar="SCIENTIFIC_NAME",
            help="Limit generation to a scientific name; repeat for several species.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            help="Optional random seed for reproducible fake data.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            metavar="SECONDS",
            help=(
                "Create one live detection every SECONDS instead of bulk "
                "history, for testing the SSE stream."
            ),
        )

    def handle(self, *args, **options):
        count = options["count"]
        hours = options["hours"]
        minimum = options["min_confidence"]
        maximum = options["max_confidence"]
        interval = options["interval"]

        if not 1 <= count <= 10_000:
            raise CommandError("--count must be between 1 and 10000.")
        if hours <= 0:
            raise CommandError("--hours must be greater than 0.")
        if interval is not None and interval <= 0:
            raise CommandError("--interval must be greater than 0.")
        if not 0 <= minimum <= maximum <= 1:
            raise CommandError(
                "Confidence values must satisfy 0 <= min <= max <= 1."
            )

        try:
            device = BirdnetDevice.objects.get(identifier=options["device"])
        except BirdnetDevice.DoesNotExist as exc:
            raise CommandError(
                f'No BirdnetDevice has identifier "{options["device"]}".'
            ) from exc

        species_queryset = Species.objects.filter(is_active=True).exclude(
            scientific_name=""
        )
        requested_species = options["species"]
        if requested_species:
            species_queryset = species_queryset.filter(
                scientific_name__in=requested_species
            )

        species_rows = list(species_queryset.only("id", "scientific_name"))
        if not species_rows:
            raise CommandError("No matching active Species rows are available.")

        if requested_species:
            found_names = {species.scientific_name for species in species_rows}
            missing_names = sorted(set(requested_species) - found_names)
            if missing_names:
                raise CommandError(
                    "Unknown or inactive species: " + ", ".join(missing_names)
                )

        generator = random.Random(options["seed"])
        if interval is not None:
            for index in range(count):
                species = generator.choice(species_rows)
                detection = BirdnetDetection.objects.create(
                    device=device,
                    species=species,
                    scientific_name=species.scientific_name,
                    confidence=generator.uniform(minimum, maximum),
                    detected_at=timezone.now(),
                )
                self.stdout.write(
                    f"[{index + 1}/{count}] {detection.scientific_name} "
                    f"({detection.confidence:.0%})"
                )
                if index + 1 < count:
                    time.sleep(interval)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Streamed {count} fake BirdNET detections for "
                    f"{device.identifier}."
                )
            )
            return

        now = timezone.now()
        window_seconds = hours * 60 * 60
        detections = []

        for _ in range(count):
            species = generator.choice(species_rows)
            detections.append(
                BirdnetDetection(
                    device=device,
                    species=species,
                    scientific_name=species.scientific_name,
                    confidence=generator.uniform(minimum, maximum),
                    detected_at=now
                    - timedelta(seconds=generator.uniform(0, window_seconds)),
                )
            )

        BirdnetDetection.objects.bulk_create(detections)
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {count} fake BirdNET detections for {device.identifier}."
            )
        )
