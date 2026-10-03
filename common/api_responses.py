from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def get_default_response(
    data=None,
    message="Request successful",
    status_code=status.HTTP_200_OK,
    errors=None,
):
    """Build the standard response envelope for any HTTP status."""
    is_success = status.HTTP_200_OK <= status_code < status.HTTP_400_BAD_REQUEST
    return Response(
        {
            "success": is_success,
            "message": message,
            "data": data,
            "errors": errors,
        },
        status=status_code,
    )


def get_response_200(data=None, message="Request successful"):
    """Build a standard 200 response with optional result data."""
    return get_default_response(data=data, message=message)


def get_response_201(data=None, message="Resource created successfully"):
    """Build a standard 201 response for a newly created resource."""
    return get_default_response(
        data=data,
        message=message,
        status_code=status.HTTP_201_CREATED,
    )


def get_response_400(errors=None, message="Validation failed"):
    """Build a standard 400 response and include validation errors."""
    return get_default_response(
        message=message,
        status_code=status.HTTP_400_BAD_REQUEST,
        errors=errors,
    )


def get_response_404(message="Resource not found", errors=None):
    """Build a standard 404 response for a missing resource."""
    return get_default_response(
        message=message,
        status_code=status.HTTP_404_NOT_FOUND,
        errors=errors,
    )


def response_body(data, status_code):
    """Normalize an existing DRF response body into the standard envelope."""
    if isinstance(data, dict) and {"success", "message", "data", "errors"}.issubset(
        data
    ):
        return data

    if status_code >= status.HTTP_400_BAD_REQUEST:
        detail = data.get("detail") if isinstance(data, dict) else None
        if status_code == status.HTTP_400_BAD_REQUEST:
            message = "Validation failed"
        elif status_code == status.HTTP_404_NOT_FOUND:
            message = str(detail or "Resource not found")
        else:
            message = str(detail or "Request failed")
        return {
            "success": False,
            "message": message,
            "data": None,
            "errors": data,
        }

    message = (
        "Resource created successfully"
        if status_code == status.HTTP_201_CREATED
        else "Request successful"
    )
    return {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
    }


def api_exception_handler(exc, context):
    """Wrap handled DRF exceptions while preserving their HTTP status codes."""
    response = exception_handler(exc, context)
    if response is not None:
        response.data = response_body(response.data, response.status_code)
    return response
