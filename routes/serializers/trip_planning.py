"""Serializers for requesting and displaying trip plans."""

from rest_framework import serializers


class TripPlanRequestSerializer(serializers.Serializer):
    """Validate origin and destination values supplied to the trip planner."""

    origin = serializers.CharField(
        max_length=255, allow_blank=False, trim_whitespace=True
    )
    destination = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        """Reject a request that names the same origin and destination."""
        if attrs["origin"].casefold() == attrs["destination"].casefold():
            raise serializers.ValidationError(
                {"destination": "Destination must differ from origin."}
            )
        return attrs


class TripLocationSerializer(serializers.Serializer):
    """Serialize a geocoded endpoint for map display."""

    label = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class FuelStopResultSerializer(serializers.Serializer):
    """Serialize one recommended stop, including a map-ready location."""

    sequence = serializers.IntegerField()
    station = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    distance_from_start_miles = serializers.DecimalField(
        max_digits=9,
        decimal_places=2,
    )
    gallons_to_buy = serializers.DecimalField(max_digits=7, decimal_places=3)
    price_per_gallon = serializers.DecimalField(max_digits=7, decimal_places=4)
    estimated_cost = serializers.DecimalField(max_digits=10, decimal_places=2)


class TripPlanResponseSerializer(serializers.Serializer):
    """Serialize the route, recommended fuel stops, and estimated stop costs."""

    trip_id = serializers.IntegerField()
    origin = TripLocationSerializer()
    destination = TripLocationSerializer()
    route_distance_miles = serializers.DecimalField(max_digits=9, decimal_places=2)
    route_geometry = serializers.JSONField()
    fuel_stops = FuelStopResultSerializer(many=True)
    total_fuel_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
