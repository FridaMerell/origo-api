"""Signal wiring for the accounts app (connected from ``AccountsConfig.ready``)."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts import tasks
from accounts.models import Notification


@receiver(post_save, sender=Notification, dispatch_uid="accounts_notification_web_push")
def push_new_notification(sender, instance, created, raw=False, **kwargs):
    """Fan a freshly created notification out to the recipient's browsers."""
    if raw or not created:
        return
    notification_pk = instance.pk
    transaction.on_commit(
        lambda: tasks.send_web_push_for_notification.enqueue(notification_pk)
    )
