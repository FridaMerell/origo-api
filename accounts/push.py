"""Web Push (VAPID) delivery for account notifications.

The subscription rows live in :class:`accounts.models.WebPushSubscription`; the
frontend service worker reads exactly the payload fields built by
:func:`build_notification_payload`. Delivery runs off the request cycle via the
``send_web_push_for_notification`` task in :mod:`accounts.tasks`; the
``/push-subscriptions/test/`` endpoint calls :func:`send_payload_to_user`
synchronously because it only hits the caller's own devices.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Notification.domain is also the frontend subdomain for that product area.
_DOMAIN_LABELS = {"verso": "Verso", "flux": "Flux", "tempus": "Tempus", "apsis": "Apsis"}

PUSH_TTL = 86_400


def tenant_root_url(tenant):
    """Absolute URL of a tenant frontend, e.g. ``https://tempus.origo.test/``."""
    return f"https://{tenant}.{settings.ROOT_DOMAIN}/"


def build_notification_payload(notification):
    """Payload dict for one :class:`~accounts.models.Notification`.

    ``Notification`` has no separate title, so the first line of the message
    becomes the title and the rest becomes the body.
    """
    lines = [line for line in notification.message.splitlines() if line.strip()]
    label = _DOMAIN_LABELS.get(notification.domain, notification.domain.title())
    if lines:
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip() or title
    else:
        title = label
        body = notification.message.strip()
    tenant = notification.domain
    return {
        "title": title,
        "body": body,
        "url": tenant_root_url(tenant),
        "tag": f"notification-{notification.pk}",
        "notificationId": str(notification.pk),
        "icon": f"/{tenant}/icon.png",
    }


def _deliver(subscription, payload):
    """Send one payload to one subscription. Returns ``True`` on success.

    Prunes the row (``is_active = False``) when the push service reports the
    endpoint gone (404/410); leaves it in place for any other error.
    """
    from pywebpush import WebPushException, webpush

    if not settings.WEBPUSH_VAPID_PRIVATE_KEY:
        logger.warning("WEBPUSH_VAPID_PRIVATE_KEY not configured; skipping push")
        return False

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.WEBPUSH_VAPID_SUBJECT},
            ttl=PUSH_TTL,
            headers={"Urgency": "normal"},
        )
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            subscription.is_active = False
            subscription.save(update_fields=["is_active"])
            logger.info("push endpoint gone (%s); deactivated %s", status_code, subscription.pk)
        elif status_code == 429:
            retry_after = exc.response.headers.get("Retry-After") if exc.response else None
            logger.warning("push rate limited (Retry-After=%s) for %s", retry_after, subscription.pk)
        else:
            logger.error("push failed for %s: %s", subscription.pk, exc)
        return False
    except Exception:  # noqa: BLE001 - never let delivery break the caller
        logger.exception("unexpected push error for %s", subscription.pk)
        return False

    subscription.last_success_at = timezone.now()
    subscription.save(update_fields=["last_success_at"])
    return True


def send_payload_to_user(user, payload):
    """Deliver ``payload`` to every active subscription of ``user``.

    Returns ``(sent, dead)`` counts.
    """
    subscriptions = list(user.push_subscriptions.filter(is_active=True))
    sent = 0
    dead = 0
    for subscription in subscriptions:
        if _deliver(subscription, payload):
            sent += 1
        elif not subscription.is_active:
            dead += 1
    logger.info(
        "web push to user %s: %d subscription(s), %d sent, %d dead",
        user.pk,
        len(subscriptions),
        sent,
        dead,
    )
    return sent, dead
