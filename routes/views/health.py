from rest_framework.permissions import AllowAny

from common.api_responses import get_response_200
from common.api_views import BaseGenericAPIView


class HealthCheckView(BaseGenericAPIView):
    permission_classes = (AllowAny,)

    def get(self, _request):
        """Return a liveness response for service monitoring."""
        return get_response_200(
            data={"status": "ok"},
            message="Service is healthy",
        )
