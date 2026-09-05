"""BirdNET device ingest and the live detection SSE stream."""
import json
import logging
import time
import uuid
from datetime import timedelta

import psycopg
from django.db import close_old_connections, connection
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from tempus.serializers import BirdnetDetectionSerializer, BirdnetDeviceSerializer
from tempus.models import BIRDNET_DETECTION_CHANNEL, BirdnetDetection, BirdnetDevice

logger = logging.getLogger(__name__)


class BirdnetDetectionIngestView(APIView):
    """Ingest endpoint for BirdNET field devices.

    Devices authenticate with a DRF token (``Authorization: Token <key>``).
    One detection per POST; responds 201 with the stored row.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BirdnetDetectionSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# --- BirdNET live stream -----------------------------------------------------

BIRDNET_STREAM_HEARTBEAT_SECONDS = 15
BIRDNET_STREAM_DEVICE_REFRESH_SECONDS = 60
BIRDNET_STREAM_POLL_SECONDS = 1
BIRDNET_STREAM_BATCH = 200
# OPTIONS keys Django's PostgreSQL backend consumes itself - they are not
# libpq keywords and psycopg.connect() would reject them.
_NON_LIBPQ_OPTIONS = {
    "pool",
    "server_side_binding",
    "isolation_level",
    "assume_role",
}


class ServerSentEventRenderer(BaseRenderer):
    """Lets DRF content negotiation accept ``Accept: text/event-stream``.

    ``EventSource`` sends that Accept header; without a matching renderer the
    request is rejected with 406 before the view runs. The view returns a raw
    ``StreamingHttpResponse``, so ``render`` is never actually called.
    """

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None or isinstance(data, (bytes, str)):
            return data
        # Only reached for an error Response (e.g. 401/403) on this endpoint.
        return json.dumps(data).encode()


def _close_quietly(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def _birdnet_listen_connection():
    """A dedicated autocommit psycopg connection ``LISTEN``ing for detections.

    Separate from the ORM connection: it blocks in ``LISTEN`` for the whole
    lifetime of one SSE response and must never be shared. Built from the
    default database's settings so it honours ``DATABASE_URL``.
    """
    db = connection.settings_dict
    params = {
        "dbname": db["NAME"] or None,
        "user": db["USER"] or None,
        "password": db["PASSWORD"] or None,
        "host": db["HOST"] or None,
        "port": db["PORT"] or None,
    }
    for key, value in (db.get("OPTIONS") or {}).items():
        if key not in _NON_LIBPQ_OPTIONS and isinstance(value, (str, int)):
            params[key] = value
    conn = psycopg.connect(autocommit=True, **params)
    try:
        conn.execute(f"LISTEN {BIRDNET_DETECTION_CHANNEL}")
    except Exception:
        conn.close()
        raise
    return conn


def _birdnet_user_device_ids(user_id):
    return {
        str(pk)
        for pk in BirdnetDevice.objects.filter(users=user_id).values_list(
            "id", flat=True
        )
    }


def _birdnet_notify_device_id(note):
    try:
        return json.loads(note.payload).get("device_id")
    except (TypeError, ValueError, AttributeError):
        return None


def _birdnet_new_events(user_id, cursor):
    """SSE chunks for detections after ``cursor``; advances ``cursor`` in place."""
    detections = list(
        BirdnetDetection.objects.filter(device__users=user_id)
        .filter(
            Q(created_at__gt=cursor["time"])
            | Q(created_at=cursor["time"], id__gt=cursor["id"])
        )
        .select_related("device", "species")
        .order_by("created_at", "id")[:BIRDNET_STREAM_BATCH]
    )
    chunks = []
    for detection in detections:
        cursor["time"] = detection.created_at
        cursor["id"] = detection.id
        event_id = f"{detection.created_at.isoformat()}|{detection.id}"
        data = json.dumps(BirdnetDetectionSerializer(detection).data)
        chunks.append(f"id: {event_id}\nevent: detection\ndata: {data}\n\n")
    return chunks


class BirdnetDetectionStreamView(APIView):
    """Stream detections for the authenticated user's devices over SSE.

    On PostgreSQL the loop blocks on a ``LISTEN``/``NOTIFY`` signal (channel
    ``birdnet_detection``, emitted by a ``post_save`` signal once the row
    commits) and confirms every wake with a cursor query, so nothing is missed
    or duplicated. It falls back to one-second polling when the backend is not
    PostgreSQL, or when the listen connection cannot be opened or is lost
    mid-stream.
    """

    permission_classes = [permissions.IsAuthenticated]
    renderer_classes = [ServerSentEventRenderer]

    def perform_content_negotiation(self, request, force=False):
        # SSE only - never 406 on a mismatched or absent Accept header.
        return ServerSentEventRenderer(), ServerSentEventRenderer.media_type

    def get(self, request):
        user_id = request.user.pk
        cursor_time, cursor_id = self._initial_cursor(request)

        def event_stream():
            cursor = {"time": cursor_time, "id": cursor_id}
            listen_conn = None
            if connection.vendor == "postgresql":
                try:
                    listen_conn = _birdnet_listen_connection()
                except Exception:  # noqa: BLE001 - degrade to polling
                    logger.warning(
                        "BirdNET SSE: LISTEN connection unavailable; polling",
                        exc_info=True,
                    )

            device_ids = set()
            device_ids_at = 0.0
            last_heartbeat = time.monotonic()
            try:
                close_old_connections()
                for chunk in _birdnet_new_events(user_id, cursor):
                    yield chunk
                last_heartbeat = time.monotonic()

                while True:
                    woke = False
                    now = time.monotonic()

                    if listen_conn is not None:
                        if (
                            now - device_ids_at
                            >= BIRDNET_STREAM_DEVICE_REFRESH_SECONDS
                        ):
                            close_old_connections()
                            device_ids = _birdnet_user_device_ids(user_id)
                            device_ids_at = now
                            woke = True
                        try:
                            for note in listen_conn.notifies(
                                timeout=BIRDNET_STREAM_HEARTBEAT_SECONDS,
                                stop_after=1,
                            ):
                                device_id = _birdnet_notify_device_id(note)
                                if device_id is None or device_id in device_ids:
                                    woke = True
                        except Exception:  # noqa: BLE001 - degrade to polling
                            logger.warning(
                                "BirdNET SSE: LISTEN connection lost; polling",
                                exc_info=True,
                            )
                            _close_quietly(listen_conn)
                            listen_conn = None
                            woke = True
                    else:
                        time.sleep(BIRDNET_STREAM_POLL_SECONDS)
                        woke = True

                    if woke:
                        close_old_connections()
                        chunks = _birdnet_new_events(user_id, cursor)
                        for chunk in chunks:
                            yield chunk
                        if chunks:
                            last_heartbeat = time.monotonic()

                    if (
                        time.monotonic() - last_heartbeat
                        >= BIRDNET_STREAM_HEARTBEAT_SECONDS
                    ):
                        yield ": keep-alive\n\n"
                        last_heartbeat = time.monotonic()
            finally:
                _close_quietly(listen_conn)
                close_old_connections()

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def _initial_cursor(request):
        event_id = request.headers.get("Last-Event-ID", "")
        if "|" in event_id:
            raw_time, raw_id = event_id.rsplit("|", 1)
            parsed_time = parse_datetime(raw_time)
            try:
                parsed_id = uuid.UUID(raw_id)
            except ValueError:
                parsed_id = None
            if parsed_time is not None and parsed_id is not None:
                return parsed_time, parsed_id

        try:
            replay_seconds = max(
                0,
                min(int(request.query_params.get("replay_seconds", 0)), 86_400),
            )
        except (TypeError, ValueError):
            replay_seconds = 0
        return timezone.now() - timedelta(seconds=replay_seconds), uuid.UUID(int=0)


class BirdnetDeviceViewSet(viewsets.ModelViewSet):
    serializer_class = BirdnetDeviceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            BirdnetDevice.objects.filter(users=self.request.user)
            .select_related("house")
            .prefetch_related("users")
            .distinct()
        )

    def perform_create(self, serializer):
        device = serializer.save()
        device.users.add(self.request.user)
