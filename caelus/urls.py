from django.urls import path

from caelus.views import cloud_cover, event_alert, kp_index, meteor_showers

app_name = "caelus"

urlpatterns = [
    path("event-alert/", event_alert, name="event-alert"),
    path("kp-index/", kp_index, name="kp-index"),
    path("cloud-cover/", cloud_cover, name="cloud-cover"),
    path("meteor-showers/", meteor_showers, name="meteor-showers"),
]
