"""Background tasks for account-level notifications."""

import logging
from html import escape
from uuid import uuid4

import requests
from django.conf import settings
from django_tasks import task

from accounts.models import Notification


logger = logging.getLogger(__name__)


def _send_resend_email(*, recipient, subject, text, html, idempotency_key):
    if not settings.RESEND_API_KEY or not settings.RESEND_FROM_EMAIL:
        return {"sent": False, "reason": "resend_not_configured"}

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "origo-notifications/1.0",
        },
        json={
            "from": settings.RESEND_FROM_EMAIL,
            "to": [recipient],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=10,
    )
    response.raise_for_status()
    return {"sent": True, "resend_id": response.json().get("id")}


@task()
def send_notification_email(notification_pk):
    """Send one existing in-app notification through Resend."""
    notification = (
        Notification.objects.select_related("user", "sent_by")
        .filter(pk=notification_pk)
        .first()
    )
    if notification is None:
        return {"sent": False, "reason": "notification_not_found"}
    if not notification.user.email:
        return {"sent": False, "reason": "recipient_has_no_email"}
    sender = notification.sent_by.get_full_name() if notification.sent_by else "Origo"
    sender = sender or (notification.sent_by.username if notification.sent_by else "Origo")
    subject = f"Ny notifikation från {notification.get_domain_display()}"
    text = f"{sender}\n\n{notification.message}"
    html = f"<p><strong>{escape(sender)}</strong></p><p>{escape(notification.message).replace(chr(10), '<br>')}</p>"
    result = _send_resend_email(
        recipient=notification.user.email,
        subject=subject,
        text=text,
        html=html,
        idempotency_key=f"notification-email-{notification.pk}",
    )
    if not result["sent"]:
        return result
    logger.info(
        "send_notification_email(%s): sent Resend message %s",
        notification.pk,
        result["resend_id"],
    )
    return result


@task()
def send_notification_email_test(domain, recipient_email):
    """Send a clearly marked Resend test email without creating a notification."""
    domains = {"flux": "Flux deadline", "tempus": "Tempus säsong"}
    label = domains[domain]
    message = f"Detta är ett test av e-postnotifikationer för {label}."
    result = _send_resend_email(
        recipient=recipient_email,
        subject=f"[TEST] {label}",
        text=message,
        html=f"<p>{escape(message)}</p>",
        idempotency_key=f"notification-email-test-{domain}-{uuid4().hex}",
    )
    if result["sent"]:
        logger.info("send_notification_email_test(%s): sent %s", domain, result["resend_id"])
    return result
