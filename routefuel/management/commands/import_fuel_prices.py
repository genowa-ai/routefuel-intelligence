import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from routefuel.models import FuelStation

REQUIRED_COLUMNS = {
    "OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Rack ID", "Retail Price"
}


class Command(BaseCommand):
    help = "Import the assessment fuel-price CSV into the local database."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=settings.FUEL_PRICE_CSV_CLEANED, help="CSV path (defaults to FUEL_PRICE_CSV_CLEANED).")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(
                f"Cleaned CSV file not found: {path}. "
                "Run scripts/audit_fuel_csv.py first to produce the cleaned dataset."
            )
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
                raise CommandError(f"CSV headers did not match expected schema. Found: {reader.fieldnames}")
            existing = set(FuelStation.objects.values_list("source_key", flat=True))
            to_create = []
            seen = set()
            rows = 0
            for row in reader:
                rows += 1
                try:
                    # Preserve full source precision (up to 8 decimal places)
                    price = Decimal(row["Retail Price"].strip())
                except (InvalidOperation, AttributeError) as exc:
                    raise CommandError(f"Invalid retail price on CSV row {rows + 1}") from exc
                identity = {key: (row.get(key) or "").strip() for key in sorted(REQUIRED_COLUMNS)}
                source_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
                if source_key in existing or source_key in seen:
                    continue
                seen.add(source_key)
                to_create.append(FuelStation(
                    source_key=source_key,
                    opis_truckstop_id=identity["OPIS Truckstop ID"],
                    name=identity["Truckstop Name"],
                    address=identity["Address"],
                    city=identity["City"],
                    state=identity["State"].upper(),
                    rack_id=identity["Rack ID"],
                    retail_price=price,
                ))
            FuelStation.objects.bulk_create(to_create, batch_size=1000, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(
            f"CSV processed: {rows} rows; added {len(to_create)} new records; database now has {FuelStation.objects.count()} records."
        ))
