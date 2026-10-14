from django.urls import path

from caelus.views import cloud_cover, kp_index, meteor_showers

app_name = "caelus"

urlpatterns = [
    path("kp-index/", kp_index, name="kp-index"),
    path("cloud-cover/", cloud_cover, name="cloud-cover"),
    path("meteor-showers/", meteor_showers, name="meteor-showers"),
]
