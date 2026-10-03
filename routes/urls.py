from django.urls import path

from routes.views.health import HealthCheckView

urlpatterns = [
	path("health/", HealthCheckView.as_view(), name="health-check"),
]