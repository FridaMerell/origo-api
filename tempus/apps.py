from django.apps import AppConfig


class TempusConfig(AppConfig):
    name = 'tempus'

    def ready(self):
        from tempus import signals  # noqa: F401  (registers post_save receivers)
