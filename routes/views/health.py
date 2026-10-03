from rest_framework.permissions import AllowAny

from common.api_responses import get_response_200
from common.api_views import BaseGenericAPIView
from common.swagger.decorators import  swagger_view


class HealthCheckView(BaseGenericAPIView):
    permission_classes = (AllowAny,)

    @swagger_view(
        summary="Health check",
        description="Check whether the FuelFuel API is responding.",
        tags=["Health"],
    )
    def get(self, _request):
        """Return a liveness response for service monitoring."""
        return get_response_200(
            data={"status": "ok"},
            message="Service is healthy",
        )
