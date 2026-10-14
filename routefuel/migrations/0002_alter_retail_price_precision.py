from django.db import migrations, models


class Migration(migrations.Migration):
    """Alter retail_price to preserve source precision (8 decimal places).

    The original CSV contains prices with up to 8 decimal places (e.g., 3.00733333).
    The previous field definition (max_digits=8, decimal_places=5) would truncate
    these values. This migration expands the field to max_digits=12, decimal_places=8
    to preserve the full source precision.
    """

    dependencies = [
        ("routefuel", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fuelstation",
            name="retail_price",
            field=models.DecimalField(decimal_places=8, max_digits=12),
        ),
    ]