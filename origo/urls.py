"""
URL configuration for origo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import include, path

from origo.admin import site
from tempus.views import BirdnetDetectionIngestView, BirdnetDetectionStreamView

urlpatterns = [
    path('admin/', site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/flux/', include('flux.urls')),
    path('api/verso/', include('verso.urls')),
    path('api/apsis/', include('apsis.urls')),
    path('api/tempus/', include('tempus.urls')),
    path('api/birdnet/detections', BirdnetDetectionIngestView.as_view(), name='birdnet-detections'),
    path('api/birdnet/detections/stream', BirdnetDetectionStreamView.as_view(), name='birdnet-detection-stream'),
]
