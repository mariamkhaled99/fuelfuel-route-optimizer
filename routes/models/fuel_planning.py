from django.db import models


class FuelStation(models.Model):
    opis_id = models.PositiveIntegerField(
        unique=True, help_text="Unique station identifier from OPIS."
    )
    name = models.CharField(max_length=255, help_text="Name of the fuel station.")
    address = models.CharField(
        max_length=255, blank=True, help_text="Street address or nearby intersection."
    )
    city = models.CharField(
        max_length=100, help_text="City where the station is located."
    )
    state = models.CharField(max_length=2, help_text="Two-letter state abbreviation.")
    rack_id = models.PositiveIntegerField(
        null=True, blank=True, help_text="OPIS fuel rack identifier, when available."
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Latitude in decimal degrees, when available.",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Longitude in decimal degrees, when available.",
    )

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state}"


class FuelPrice(models.Model):
    station = models.ForeignKey(
        FuelStation,
        on_delete=models.CASCADE,
        related_name="prices",
        help_text="Station this price belongs to.",
    )
    price_per_gallon = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        help_text="Retail price in dollars per gallon.",
    )


class Trip(models.Model):
    origin = models.CharField(max_length=255, help_text="Trip starting location.")
    destination = models.CharField(max_length=255, help_text="Trip ending location.")
    origin_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, help_text="Origin latitude in decimal degrees."
    )
    origin_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, help_text="Origin longitude in decimal degrees."
    )
    destination_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Destination latitude in decimal degrees.",
    )
    destination_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Destination longitude in decimal degrees.",
    )

    max_range_miles = models.PositiveSmallIntegerField(
        default=500, help_text="Maximum travel distance on a full tank, in miles."
    )
    mpg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        help_text="Vehicle fuel efficiency in miles per gallon.",
    )
    initial_fuel_gallons = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=50,
        help_text="Fuel in the tank at the start of the trip, in gallons.",
    )

    route_distance_miles = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Calculated route distance in miles.",
    )
    route_geometry = models.JSONField(
        null=True, blank=True, help_text="Calculated route geometry as GeoJSON."
    )
    estimated_fuel_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated total fuel cost in dollars.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Time when this trip was created."
    )


class TripFuelStop(models.Model):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="fuel_stops",
        help_text="Trip this fuel stop belongs to.",
    )
    station = models.ForeignKey(
        FuelStation,
        on_delete=models.PROTECT,
        related_name="trip_stops",
        help_text="Station selected for this stop.",
    )
    sequence = models.PositiveSmallIntegerField(
        help_text="Order of this stop along the trip, starting at 1."
    )
    distance_from_start_miles = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        help_text="Distance from the trip origin to this stop, in miles.",
    )
    gallons_to_buy = models.DecimalField(
        max_digits=7, decimal_places=3, help_text="Gallons to purchase at this stop."
    )
    price_per_gallon = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        help_text="Fuel price at this stop in dollars per gallon.",
    )
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Estimated purchase cost at this stop in dollars.",
    )

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("trip", "sequence"),
                name="unique_trip_fuel_stop_sequence",
            )
        ]
