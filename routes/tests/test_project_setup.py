import json

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from common.api_responses import (
    get_default_response,
    get_response_200,
    get_response_201,
    get_response_400,
    get_response_404,
)
from common.api_views import BaseGenericAPIView


@pytest.mark.parametrize(
    ("response_helper", "kwargs", "expected_status", "expected_message"),
    [
        (get_response_200, {}, 200, "Request successful"),
        (get_response_201, {}, 201, "Resource created successfully"),
        (
            get_response_400,
            {"errors": {"field": ["invalid"]}},
            400,
            "Validation failed",
        ),
        (get_response_404, {}, 404, "Resource not found"),
        (
            get_default_response,
            {"message": "Custom result", "status_code": 202},
            202,
            "Custom result",
        ),
    ],
)
def test_response_helpers_use_consistent_envelope(
    response_helper,
    kwargs,
    expected_status,
    expected_message,
):
    response = response_helper(**kwargs)

    assert response.status_code == expected_status
    assert response.data["success"] is (expected_status < 400)
    assert response.data["message"] == expected_message
    assert set(response.data) == {"success", "message", "data", "errors"}


def test_generic_api_view_wraps_plain_response():
    class PlainResponseView(BaseGenericAPIView):
        def get(self, _request):
            return Response({"status": "ok"})

    response = PlainResponseView.as_view()(APIRequestFactory().get("/"))

    assert response.data == {
        "success": True,
        "message": "Request successful",
        "data": {"status": "ok"},
        "errors": None,
    }


def test_test_environment_is_isolated():
    assert settings.ENVIRONMENT == "test"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert (
        settings.DATABASES["default"]["TEST"]["NAME"] == "test_fuelfuel_route_optimizer"
    )
    assert "nplusone.ext.django" not in settings.INSTALLED_APPS


@pytest.mark.django_db
def test_postgresql_test_database_connects():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1


def test_openapi_schema_endpoint(client):
    response = client.get("/api/schema/?format=json")

    assert response.status_code == 200
    assert json.loads(response.content)["openapi"].startswith("3.")


def test_health_check_endpoint(client):
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Service is healthy",
        "data": {"status": "ok"},
        "errors": None,
    }


def test_configured_cache_can_store_values():
    cache.set("project-setup-check", "ok", timeout=10)

    assert cache.get("project-setup-check") == "ok"
