"""Background tasks for the caelus app."""

import datetime
import logging
from datetime import timedelta

from django.utils import timezone
from django_tasks import task

from caelus.services import events, iau_mdc

logger = logging.getLogger(__name__)

# How long before an event the warning goes out.
ALERT_DAYS_AHEAD = 3
# The local hour the warnings go out, in the evening when people plan.
ALERT_HOUR = 18


def next_alert_run(now=None):
    """Return the next ``ALERT_HOUR`` o'clock in Caelus's timezone."""
    local_now = (now or timezone.now()).astimezone(events.TIME_ZONE)
    next_run = local_now.replace(hour=ALERT_HOUR, minute=0, second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


@task()
def notify_upcoming_sky_events():
    """Warn opted-in users about the notable events of the day three days ahead.

    Self-scheduling: each run re-enqueues itself for the next evening. Events
    are computed once per rounded position, so users close to each other share
    the work.
    """
    from accounts.models import Notification
    from accounts.tasks import send_notification_email
    from caelus.models import EventAlert

    now = timezone.now()
    day = now.astimezone(events.TIME_ZONE).date() + timedelta(days=ALERT_DAYS_AHEAD)
    start = datetime.datetime.combine(day, datetime.time(), tzinfo=events.TIME_ZONE)
    end = datetime.datetime.combine(
        day + timedelta(days=1), datetime.time(), tzinfo=events.TIME_ZONE
    )

    try:
        showers = iau_mdc.get_showers()
    except iau_mdc.IauMdcAPIError as exc:
        logger.warning("notify_upcoming_sky_events: no meteor showers: %s", exc)
        showers = []

    by_position = {}
    created = 0
    for alert in EventAlert.objects.select_related("user"):
        position = (round(alert.latitude), round(alert.longitude))
        if position not in by_position:
            by_position[position] = events.events_between(start, end, *position, showers)
        for event in by_position[position]:
            local = event.time.astimezone(events.TIME_ZONE)
            message = f"Om tre dagar: {event.title}\n{local.day}/{local.month} kl. {local:%H:%M}"
            if event.detail:
                message += f". {event.detail}"
            already_notified = Notification.objects.filter(
                user=alert.user,
                domain="caelus",
                message=message,
                created_at__gte=now - timedelta(days=ALERT_DAYS_AHEAD),
            ).exists()
            if already_notified:
                continue
            notification = Notification.objects.create(
                user=alert.user,
                domain="caelus",
                message=message,
            )
            send_notification_email.enqueue(notification.pk)
            created += 1

    logger.info("notify_upcoming_sky_events: created %d notification(s)", created)
    notify_upcoming_sky_events.using(run_after=next_alert_run()).enqueue()
    return {"created": created}
