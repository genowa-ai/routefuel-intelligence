from django.db import models

class FuelStation(models.Model):
    """Fuel-price row from the supplied assessment CSV.

    Coordinates are Census place representative points for the station's city,
    not the precise truck-stop entrance. This is explicit in the API response.
    """
    source_key = models.CharField(max_length=64, unique=True, db_index=True)
    opis_truckstop_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120, db_index=True)
    state = models.CharField(max_length=8, db_index=True)
    rack_id = models.CharField(max_length=32, blank=True)
    # Preserve source precision: up to 8 decimal places (e.g., 3.00733333)
    retail_price = models.DecimalField(max_digits=12, decimal_places=8)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    coordinate_source = models.CharField(max_length=40, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "city"], name="routefuel_f_state_2bd4a7_idx"),
            models.Index(fields=["latitude", "longitude"], name="routefuel_f_latitud_6f1b82_idx"),
        ]
        ordering = ["retail_price", "name"]

    def __str__(self):
        return f"{self.name} — {self.city}, {self.state} (${self.retail_price}/gal)"
