from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api_responses import response_body


class StandardizedResponseMixin:
    """Apply the common response envelope to DRF response objects."""

    def finalize_response(self, request, response, *args, **kwargs):
        """Normalize response data before DRF renders it, except for 204s."""
        if (
            isinstance(response, Response)
            and response.status_code != status.HTTP_204_NO_CONTENT
        ):
            response.data = response_body(response.data, response.status_code)
        return super().finalize_response(request, response, *args, **kwargs)


class BaseAPIView(StandardizedResponseMixin, APIView):
    """APIView base class that standardizes successful responses."""


class BaseGenericAPIView(StandardizedResponseMixin, GenericAPIView):
    """GenericAPIView base class that standardizes successful responses."""
