"""Background tasks for account-level notifications."""

import logging

import requests
from django.conf import settings
from django.template.loader import render_to_string
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
    if not response.ok:
        try:
            error = response.json().get("message", response.text)
        except ValueError:
            error = response.text
        logger.error("Resend rejected notification email: %s", error)
        return {"sent": False, "reason": f"resend_error: {error}"}
    return {"sent": True, "resend_id": response.json().get("id")}


def _email_content(notification, template_key, context):
    context = {
        "app_name": notification.get_domain_display(),
        "notification_message": notification.message,
        "recipient_name": notification.user.get_short_name() or notification.user.username,
        **(context or {}),
    }
    if template_key == "flux_deadline":
        subject = f"Deadline idag: {context['task_title']}"
        preheader = f"{context['task_title']} i {context['project_name']} har deadline idag."
    elif template_key == "tempus_season":
        species_count = len(context["species_names"])
        subject = (
            f"Säsongsstart om 7–14 dagar: {context['species_names'][0]}"
            if species_count == 1
            else f"Säsongsstart om 7–14 dagar för {species_count} följda arter"
        )
        preheader = "En säsongsnotifikation från Tempus."
    else:
        template_key = "generic"
        subject = f"Ny notifikation från {context['app_name']}"
        preheader = notification.message.splitlines()[0]

    context.update(email_title=subject, preheader=preheader)
    text = render_to_string(f"accounts/email/{template_key}.txt", context).strip()
    html = render_to_string(f"accounts/email/{template_key}.html", context)
    return subject, text, html


def send_notification_email_now(notification_pk, template_key="generic", context=None):
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
    subject, text, html = _email_content(notification, template_key, context)
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
def send_notification_email(notification_pk, template_key="generic", context=None):
    """Queueable wrapper for delivery of one existing notification."""
    return send_notification_email_now(notification_pk, template_key, context)
