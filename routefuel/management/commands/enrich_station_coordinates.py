import csv
import io
import re
import zipfile
from pathlib import Path
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from routefuel.models import FuelStation

CACHE_DIR = Path(settings.BASE_DIR) / "data" / "geo_cache"
SUFFIXES = {"city", "town", "village", "borough", "cdp", "municipality", "plantation", "metropolitan", "balance", "urban county"}


def normalize_place(value):
    value = re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())
    tokens = " ".join(value.split()).split()
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def read_gazetteer(source_path=None):
    """Return {(state abbreviation, normalized place): (lat, lon)}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if source_path:
        path = Path(source_path)
        if not path.is_file():
            raise CommandError(f"Gazetteer file not found: {path}")
        raw = path.read_bytes()
    else:
        cached = CACHE_DIR / "2026_Gaz_place_national.zip"
        if cached.exists() and cached.stat().st_size > 100_000:
            raw = cached.read_bytes()
        else:
            try:
                response = requests.get(settings.CENSUS_GAZETTEER_URL, timeout=(5, 45), headers={"User-Agent": "FuelRouteOptimizerAssessment/1.0"})
                response.raise_for_status()
                raw = response.content
            except requests.RequestException as exc:
                raise CommandError(f"Could not download the US Census Gazetteer: {exc}") from exc
            if not raw.startswith(b"PK"):
                raise CommandError("Census Gazetteer download did not look like a ZIP archive.")
            cached.write_bytes(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith((".txt", ".dat", ".csv"))]
            if not candidates:
                raise CommandError("No text file found in the Gazetteer ZIP archive.")
            with archive.open(candidates[0]) as stream:
                text = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace")
                reader = csv.DictReader(text, delimiter="|")
                if not reader.fieldnames:
                    raise CommandError("Gazetteer has no header row.")
                headers = {h.strip().upper() for h in reader.fieldnames}
                needed = {"USPS", "NAME", "INTPTLAT", "INTPTLONG"}
                if not needed.issubset(headers):
                    raise CommandError(f"Unrecognized Gazetteer columns: {reader.fieldnames}")
                # DictReader preserves original case of header names, so locate columns case-insensitively.
                original = {h.strip().upper(): h for h in reader.fieldnames}
                lookup = {}
                for row in reader:
                    state = (row.get(original["USPS"]) or "").strip().upper()
                    name = row.get(original["NAME"]) or ""
                    try:
                        lat = float(row[original["INTPTLAT"]])
                        lon = float(row[original["INTPTLONG"]])
                    except (ValueError, TypeError):
                        continue
                    key = (state, normalize_place(name))
                    if state and key[1]:
                        lookup.setdefault(key, (lat, lon))
                return lookup
    except zipfile.BadZipFile as exc:
        raise CommandError("Gazetteer file is not a valid ZIP archive.") from exc


class Command(BaseCommand):
    help = "Enrich fuel stations with approximate US Census place representative coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--gazetteer-file", help="Optional path to a downloaded Census Gazetteer ZIP archive.")
        parser.add_argument("--report", default=str(Path(settings.BASE_DIR) / "data" / "unmatched_stations.csv"), help="Path to unmatched rows report.")

    def handle(self, *args, **options):
        if not FuelStation.objects.exists():
            raise CommandError("No fuel stations found. Run import_fuel_prices first.")
        places = read_gazetteer(options["gazetteer_file"])
        stations = list(FuelStation.objects.all().order_by("id"))
        changed, unmatched = [], []
        for station in stations:
            key = (station.state.upper(), normalize_place(station.city))
            point = places.get(key)
            if not point:
                # Some datasets abbreviate a town/place; retry with only a city name and exact US state.
                point = places.get((station.state.upper(), normalize_place(station.city.replace("St.", "Saint"))))
            if point and station.state.upper() not in {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}:
                station.latitude, station.longitude = point
                station.coordinate_source = "census_2026_place_point"
                changed.append(station)
            elif station.state.upper() not in {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}:
                unmatched.append(station)
        FuelStation.objects.bulk_update(changed, ["latitude", "longitude", "coordinate_source"], batch_size=1000)
        report = Path(options["report"])
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Retail Price"])
            for station in unmatched:
                writer.writerow([station.opis_truckstop_id, station.name, station.address, station.city, station.state, station.retail_price])
        us_count = FuelStation.objects.filter(state__in={"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"}).count()
        enriched_us = sum(1 for s in changed if s.state.upper() not in {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"})
        self.stdout.write(self.style.SUCCESS(f"Gazetteer loaded {len(places)} place coordinates. Updated {len(changed)} station records. US records: {us_count}; US records enriched: {enriched_us}; unmatched US records: {len(unmatched)}."))
        self.stdout.write(f"Unmatched station report written to: {report}")
        self.stdout.write("Note: these are city representative points, not exact fuel station coordinates.")
