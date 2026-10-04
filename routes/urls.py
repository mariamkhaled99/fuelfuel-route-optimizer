from django.urls import path

from routes.views.health import HealthCheckView
from routes.views.trip_planning import TripPlanView, trip_planner_page

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("trips/plan/", TripPlanView.as_view(), name="trip-plan"),
    path("trip-planner/", trip_planner_page, name="trip-planner-page"),
]
