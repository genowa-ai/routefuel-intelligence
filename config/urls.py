from django.contrib import admin
from django.urls import include, path
from routefuel.views import health, map_preview

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("map/", map_preview, name="map-preview"),
    path("api/v1/", include("routefuel.urls")),
]
