from django.urls import path
from .views import RouteFuelAPIView

urlpatterns = [
    path("route-fuel/", RouteFuelAPIView.as_view(), name="route-fuel"),
]
