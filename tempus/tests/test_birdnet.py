"""BirdNET detection ingest (REST) and the live detection stream (SSE).

The stream view runs an endless generator; every test pulls exactly the number
of frames the seeded data should produce and then closes the response. If the
generator ever reaches its poll loop within a test, the patched ``time.sleep``
turns the hang into an immediate failure.
"""

import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from tempus.models import BirdnetDetection, BirdnetDevice, Species

User = get_user_model()

STREAM_URL = "/api/birdnet/detections/stream"
INGEST_URL = "/api/birdnet/detections"


def read_sse_events(response, count):
    """Pull ``count`` frames from a streaming SSE response, then close it."""
    iterator = iter(response.streaming_content)

    def _no_poll(*_args, **_kwargs):
        raise AssertionError("SSE generator polled past the initial batch")

    frames = []
    try:
        with mock.patch("tempus.views.time.sleep", _no_poll):
            for _ in range(count):
                frames.append(next(iterator).decode())
    finally:
        iterator.close()
        response.close()
    return frames


def parse_sse(frame):
    fields = {}
    for line in frame.splitlines():
        if not line or line.startswith(":"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.lstrip()
    if "data" in fields:
        fields["data"] = json.loads(fields["data"])
    return fields


class BirdnetTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="x")
        self.other = User.objects.create_user(username="stranger", password="x")

        self.device = BirdnetDevice.objects.create(
            identifier="pi-birdnet-001", name="Garden mic"
        )
        self.device.users.add(self.user)

        self.other_device = BirdnetDevice.objects.create(
            identifier="pi-birdnet-999", name="Someone else's mic"
        )
        self.other_device.users.add(self.other)

        self.blackbird = Species.objects.create(
            dyntaxa_taxon_id=103026,
            scientific_name="Turdus merula",
            swedish_name="Koltrast",
        )
        self.base = timezone.now().replace(microsecond=0) - timedelta(minutes=10)

    def make_detection(self, device, name, *, offset, species=None, confidence=0.9):
        """Create a detection whose ``created_at`` is ``base + offset`` seconds."""
        detection = BirdnetDetection.objects.create(
            device=device,
            species=species,
            scientific_name=name,
            confidence=confidence,
            detected_at=self.base + timedelta(seconds=offset),
        )
        stamped = self.base + timedelta(seconds=offset)
        BirdnetDetection.objects.filter(pk=detection.pk).update(created_at=stamped)
        detection.refresh_from_db()
        return detection

    def stream(self, **extra):
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client.get(STREAM_URL, {"replay_seconds": 86400}, **extra)


class IngestTests(BirdnetTestBase):
    def _post(self, token, body):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client.post(INGEST_URL, body, format="json")

    def test_valid_post_creates_detection_and_matches_species(self):
        token = Token.objects.create(user=self.user)
        response = self._post(
            token,
            {
                "species": "turdus merula",  # case-insensitive match
                "confidence": 0.87,
                "detectedAt": timezone.now().isoformat(),
                "device_id": "pi-birdnet-001",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        detection = BirdnetDetection.objects.get()
        self.assertEqual(detection.scientific_name, "turdus merula")
        self.assertEqual(detection.species, self.blackbird)
        self.assertEqual(detection.device, self.device)

        matched = response.data["matched_species"]
        self.assertEqual(matched["dyntaxa_taxon_id"], 103026)
        self.assertEqual(matched["swedish_name"], "Koltrast")

    def test_unmatched_species_is_stored_with_null_match(self):
        token = Token.objects.create(user=self.user)
        response = self._post(
            token,
            {
                "species": "Nonexistent species",
                "confidence": 0.4,
                "detectedAt": timezone.now().isoformat(),
                "device_id": "pi-birdnet-001",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["matched_species"])
        self.assertIsNone(BirdnetDetection.objects.get().species)

    def test_unknown_or_unauthorised_device_is_rejected(self):
        token = Token.objects.create(user=self.user)
        response = self._post(
            token,
            {
                "species": "Turdus merula",
                "confidence": 0.9,
                "detectedAt": timezone.now().isoformat(),
                "device_id": "pi-birdnet-999",  # not this user's device
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("device_id", response.data)
        self.assertFalse(BirdnetDetection.objects.exists())

    def test_anonymous_post_is_unauthorised(self):
        response = APIClient().post(
            INGEST_URL,
            {
                "species": "Turdus merula",
                "confidence": 0.9,
                "detectedAt": timezone.now().isoformat(),
                "device_id": "pi-birdnet-001",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 401)


class StreamContentNegotiationTests(BirdnetTestBase):
    def test_event_stream_accept_header_is_not_406(self):
        response = self.stream(HTTP_ACCEPT="text/event-stream")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("text/event-stream"))
            self.assertEqual(response["Cache-Control"], "no-cache")
            self.assertEqual(response["X-Accel-Buffering"], "no")
        finally:
            response.close()

    def test_json_accept_header_still_streams(self):
        response = self.stream(HTTP_ACCEPT="application/json")
        try:
            self.assertEqual(response.status_code, 200)
        finally:
            response.close()

    def test_anonymous_stream_is_denied(self):
        response = APIClient().get(STREAM_URL)
        response.close()
        self.assertIn(response.status_code, (401, 403))


class StreamContentTests(BirdnetTestBase):
    def test_replays_only_the_users_own_devices(self):
        mine_1 = self.make_detection(self.device, "Turdus merula", offset=0)
        # A stranger's detection, timestamped between mine - it must not leak.
        self.make_detection(self.other_device, "Corvus corax", offset=30)
        mine_2 = self.make_detection(self.device, "Erithacus rubecula", offset=60)

        frames = [parse_sse(f) for f in read_sse_events(self.stream(), 2)]

        ids = [f["data"]["id"] for f in frames]
        self.assertEqual(ids, [str(mine_1.id), str(mine_2.id)])
        self.assertTrue(all(f["event"] == "detection" for f in frames))
        self.assertTrue(all(f["data"]["device_id"] == "pi-birdnet-001" for f in frames))

    def test_payload_carries_matched_species_and_nulls_when_unmatched(self):
        self.make_detection(
            self.device, "Turdus merula", offset=0, species=self.blackbird
        )
        self.make_detection(self.device, "Totally unknown bird", offset=10)

        matched, unmatched = (
            parse_sse(f)["data"] for f in read_sse_events(self.stream(), 2)
        )

        self.assertEqual(matched["species"], "Turdus merula")
        self.assertEqual(matched["matched_species"]["swedish_name"], "Koltrast")
        self.assertEqual(matched["matched_species"]["dyntaxa_taxon_id"], 103026)
        self.assertIsNone(unmatched["matched_species"])

    def test_last_event_id_resumes_after_that_row(self):
        first = self.make_detection(self.device, "Turdus merula", offset=0)
        second = self.make_detection(self.device, "Erithacus rubecula", offset=20)
        third = self.make_detection(self.device, "Parus major", offset=40)

        last_event_id = f"{first.created_at.isoformat()}|{first.id}"
        response = self.stream(HTTP_LAST_EVENT_ID=last_event_id)
        frames = [parse_sse(f) for f in read_sse_events(response, 2)]

        self.assertEqual(
            [f["data"]["id"] for f in frames], [str(second.id), str(third.id)]
        )

    def test_event_id_line_is_created_at_and_uuid(self):
        detection = self.make_detection(self.device, "Turdus merula", offset=0)
        frame = parse_sse(read_sse_events(self.stream(), 1)[0])
        self.assertEqual(
            frame["id"], f"{detection.created_at.isoformat()}|{detection.id}"
        )
