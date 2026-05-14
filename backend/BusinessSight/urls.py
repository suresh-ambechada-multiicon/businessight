from django.urls import path

from analytics.api import api

urlpatterns = [
    path("api/v1/", api.urls),
]
