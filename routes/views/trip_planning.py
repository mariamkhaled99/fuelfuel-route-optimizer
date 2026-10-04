"""HTTP endpoints for building fuel-efficient trip plans."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from django.shortcuts import render
from common.api_responses import (
    get_default_response,
    get_response_200,
    get_response_400,
)
from common.api_views import BaseGenericAPIView
from common.swagger.decorators import swagger_view
from routes.services.fuel_planning import FuelStopPlanningError
from routes.serializers.trip_planning import (
    TripPlanRequestSerializer,
    TripPlanResponseSerializer,
)
from routes.services.trip_planning import (
    TripLocationNotFoundError,
    TripPlanningProviderError,
    TripRouteNotFoundError,
    build_trip_plan,
)


class TripPlanView(BaseGenericAPIView):
    """Create and return an optimized multi-stop driving itinerary."""

    permission_classes = (AllowAny,)
    serializer_class = TripPlanRequestSerializer

    @swagger_view(
        summary="Plan a fuel-efficient U.S. trip",
        description=(
            "Geocodes U.S. origin and destination names, requests a driving route, "
            "and returns GeoJSON route geometry with cost-conscious fuel stops. "
            "The vehicle range is 500 miles and efficiency is 10 MPG."
        ),
        tags=["Trips"],
        request=TripPlanRequestSerializer,
        responses={200: TripPlanResponseSerializer},
    )
    def post(self, request):
        """Validate a trip request and return its route and fuel-stop plan."""
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            result = build_trip_plan(**request_serializer.validated_data)
        except TripLocationNotFoundError as exc:
            return get_response_400(
                errors={"location": str(exc)},
                message="A requested U.S. location could not be found",
            )
        except TripRouteNotFoundError as exc:
            return get_default_response(
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"route": str(exc)},
            )
        except FuelStopPlanningError as exc:
            return get_default_response(
                message="A complete fuel-stop itinerary could not be planned",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"fuel_stops": str(exc)},
            )
        except TripPlanningProviderError as exc:
            return get_default_response(
                message="A map provider could not complete the request",
                status_code=status.HTTP_502_BAD_GATEWAY,
                errors={"provider": str(exc)},
            )

        response_serializer = TripPlanResponseSerializer(result)
        return get_response_200(
            data=response_serializer.data,
            message="Trip route and fuel stops planned successfully",
        )


def trip_planner_page(request):
    """Render the browser-based form and GeoJSON route map."""

    return render(request, "routes/trip_planner.html")
