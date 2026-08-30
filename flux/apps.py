from django.apps import AppConfig


class FluxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'flux'

    def ready(self):
        from flux import signals  # noqa: F401  (registers task receivers)
