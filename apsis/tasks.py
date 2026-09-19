"""Scheduled newsletter delivery for Apsis."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django_tasks import task

from accounts.models import Notification
from accounts.tasks import send_notification_email
from apsis.models import Post


def next_newsletter_run(now=None):
    """Return the next Monday at 08:00 in the newsletter's local timezone."""
    local_now = (now or timezone.now()).astimezone(
        ZoneInfo(settings.APSIS_NEWSLETTER_TIME_ZONE)
    )
    days_until_monday = -local_now.weekday() % 7
    next_run = (local_now + timedelta(days=days_until_monday)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    if next_run <= local_now:
        next_run += timedelta(days=7)
    return next_run


def _newsletter_message(post):
    title = post.name or "Veckans absid"
    location = f"\nPlats: {post.geolocation}" if post.geolocation else ""
    return f"Här är veckans absid: {title}\n\n{post.content}{location}"


@task()
def send_weekly_apsis_newsletter():
    """Notify users about the latest weekly apse post and re-schedule."""
    try:
        post = (
            Post.objects.filter(
                has_apsis=True,
                created_at__gte=timezone.now() - timedelta(days=7),
            )
            .order_by("-created_at")
            .first()
        )
        if post is None:
            return {"sent": 0, "reason": "no_apsis_post_this_week"}
        user_model = get_user_model()
        notifications = []
        for user in user_model.objects.filter(is_active=True):
            notification = Notification.objects.create(
                user=user,
                domain="apsis",
                message=_newsletter_message(post),
            )
            notifications.append(notification.pk)

        for notification_pk in notifications:
            transaction.on_commit(
                lambda pk=notification_pk: send_notification_email.enqueue(
                    pk, "apsis_weekly"
                )
            )
        return {"notifications": len(notifications), "post_id": post.pk}
    finally:
        send_weekly_apsis_newsletter.using(
            run_after=next_newsletter_run()
        ).enqueue()
