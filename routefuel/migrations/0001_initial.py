from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_key", models.CharField(db_index=True, max_length=64, unique=True)),
                ("opis_truckstop_id", models.CharField(db_index=True, max_length=32)),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(db_index=True, max_length=120)),
                ("state", models.CharField(db_index=True, max_length=8)),
                ("rack_id", models.CharField(blank=True, max_length=32)),
                ("retail_price", models.DecimalField(decimal_places=5, max_digits=8)),
                ("latitude", models.FloatField(blank=True, null=True)),
                ("longitude", models.FloatField(blank=True, null=True)),
                ("coordinate_source", models.CharField(blank=True, max_length=40)),
            ],
            options={"ordering": ["retail_price", "name"]},
        ),
        migrations.AddIndex(model_name="fuelstation", index=models.Index(fields=["state", "city"], name="routefuel_f_state_2bd4a7_idx")),
        migrations.AddIndex(model_name="fuelstation", index=models.Index(fields=["latitude", "longitude"], name="routefuel_f_latitud_6f1b82_idx")),
    ]
