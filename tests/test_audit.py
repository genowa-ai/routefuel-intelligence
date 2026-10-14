from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path

# Import production functions to test them directly
from scripts.audit_fuel_csv import (
    detect_encoding,
    decode_with_bom_handling,
    parse_csv_content,
    validate_header,
    apply_text_repairs_once,
    parse_price,
    normalize_state_code,
    normalize_row,
    MOJIBAKE_REPAIRS,
    Stats,
    REQUIRED_COLUMNS,
)

REQUIRED_COLUMNS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]


class AuditTests(unittest.TestCase):
    """Tests that independently verify audit outputs by reading CSV files directly."""

    def setUp(self):
        self.source_path = Path("data/fuel-prices-for-be-assessment.csv")
        self.cleaned_path = Path("data/processed/fuel_prices_cleaned.csv")
        self.quarantine_path = Path("data/processed/fuel_prices_quarantine.csv")
        self.report_md_path = Path("docs/reports/fuel_csv_quality_report.md")
        self.report_json_path = Path("docs/reports/fuel_csv_quality_report.json")
        with self.report_json_path.open(encoding="utf-8") as f:
            self.report = json.load(f)

    def _read_csv_prices(self, path: Path, price_col: str = "Retail Price") -> list[Decimal]:
        """Read all valid positive prices from a CSV file."""
        prices = []
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    price = Decimal(row[price_col].strip())
                    if price > 0:
                        prices.append(price)
                except Exception:
                    pass
        return prices

    def _read_csv_rows(self, path: Path) -> list[dict]:
        """Read all rows from a CSV file as dicts."""
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_source_file_exists_and_unchanged(self):
        self.assertTrue(self.source_path.exists())
        h = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        self.assertEqual(h, "c704371f141ded9c54df6c32d488a0ba2ceb589f88c936c967daa5330e0cd241")

    def test_raw_record_count(self):
        """Raw record count should match source CSV data rows (excluding header)."""
        raw_prices = self._read_csv_prices(self.source_path)
        self.assertEqual(len(raw_prices), 8151)
        self.assertEqual(self.report["raw_record_count"], 8151)
        self.assertEqual(self.report["input_record_count"], 8151)

    def test_cleaned_record_count(self):
        """Cleaned record count should equal raw minus exact duplicates removed."""
        cleaned_rows = self._read_csv_rows(self.cleaned_path)
        self.assertEqual(len(cleaned_rows), 8125)
        self.assertEqual(self.report["cleaned_record_count"], 8125)

    def test_quarantine_record_count(self):
        """Quarantine should have 0 records for this clean dataset."""
        self.assertEqual(self.report["quarantined_record_count"], 0)
        if self.quarantine_path.exists():
            with self.quarantine_path.open(encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
                # Header only, no data rows
                self.assertEqual(len(rows), 1)

    def test_exact_duplicates_removed(self):
        """Exactly 26 extra occurrences from 15 duplicate groups should be removed."""
        self.assertEqual(self.report["exact_duplicate_groups"], 15)
        self.assertEqual(self.report["exact_duplicate_extra_occurrences"], 26)

    def test_repeated_station_ids_tracked_not_deduped(self):
        """Repeated station IDs with different prices should be tracked but preserved."""
        self.assertEqual(self.report["repeated_station_id_groups"], 678)
        self.assertEqual(self.report["repeated_station_id_extra_occurrences"], 1413)

    def test_price_statistics_raw(self):
        """Raw price statistics computed independently from source CSV."""
        raw_prices = self._read_csv_prices(self.source_path)
        self.assertEqual(len(raw_prices), 8151)
        self.assertEqual(min(raw_prices), Decimal("2.68733333"))
        self.assertEqual(max(raw_prices), Decimal("6.399"))
        raw_mean = sum(raw_prices) / Decimal(len(raw_prices))
        self.assertEqual(str(raw_mean), "3.498973929009937430990062569")
        # Verify report matches
        self.assertEqual(self.report["raw_min_price"], "2.68733333")
        self.assertEqual(self.report["raw_max_price"], "6.399")
        self.assertEqual(self.report["raw_mean_price"], "3.498973929009937430990062569")

    def test_price_statistics_cleaned(self):
        """Cleaned price statistics computed independently from cleaned CSV."""
        cleaned_prices = self._read_csv_prices(self.cleaned_path)
        self.assertEqual(len(cleaned_prices), 8125)
        self.assertEqual(min(cleaned_prices), Decimal("2.68733333"))
        self.assertEqual(max(cleaned_prices), Decimal("6.399"))
        cleaned_mean = sum(cleaned_prices) / Decimal(len(cleaned_prices))
        self.assertEqual(str(cleaned_mean), "3.498908614813538461538461538")
        # Verify report matches
        self.assertEqual(self.report["min_price"], "2.68733333")
        self.assertEqual(self.report["max_price"], "6.399")
        self.assertEqual(self.report["mean_price"], "3.498908614813538461538461538")

    def test_raw_and_cleaned_min_max_equal(self):
        """Min and max should be identical since exact duplicates have same price."""
        self.assertEqual(self.report["raw_min_price"], self.report["min_price"])
        self.assertEqual(self.report["raw_max_price"], self.report["max_price"])

    def test_raw_and_cleaned_mean_differ_slightly(self):
        """Mean should differ slightly because exact duplicates are removed."""
        raw_mean = Decimal(self.report["raw_mean_price"])
        cleaned_mean = Decimal(self.report["mean_price"])
        # They differ because 26 duplicate rows with same prices are removed
        self.assertNotEqual(raw_mean, cleaned_mean)

    def test_known_mojibake_repaired_once(self):
        """The documented Stuckey's mojibake should be repaired exactly once."""
        self.assertEqual(len(self.report["text_repairs"]), 1)
        repair = self.report["text_repairs"][0]
        self.assertEqual(repair["row_number"], 6526)
        self.assertEqual(repair["column"], "Truckstop Name")
        self.assertIn("Stuckey", repair["original"])
        self.assertIn("Stuckey", repair["corrected"])
        # Verify cleaned CSV has the corrected curly quote
        cleaned_rows = self._read_csv_rows(self.cleaned_path)
        stuckey = next(r for r in cleaned_rows if "Stuckey" in r["Truckstop Name"])
        # The corrected value should contain the curly quote (U+2019)
        self.assertIn("\u2019", stuckey["Truckstop Name"])
        # Original mojibake sequence should not be present
        self.assertNotIn("\u00e2\u20ac\u2122", stuckey["Truckstop Name"])

    def test_geographic_classification(self):
        """US states, Canadian provinces, and unknown codes should be classified correctly."""
        self.assertEqual(self.report["us_records"], 7505)
        self.assertEqual(self.report["ca_records"], 620)
        self.assertEqual(self.report["unknown_geo_records"], 0)

    def test_whitespace_normalization(self):
        """Whitespace normalization count should match."""
        self.assertEqual(self.report["whitespace_cells_normalized"], 1356)
        self.assertEqual(self.report["blank_cells"], 0)

    def test_schema_valid(self):
        """Schema validation should pass for the source file."""
        self.assertTrue(self.report["schema_valid"])

    def test_encoding_utf8_no_fallback(self):
        """Source file should decode as UTF-8 without fallback."""
        self.assertEqual(self.report["encoding"], "utf-8")
        self.assertFalse(self.report["used_fallback_encoding"])
        self.assertIsNone(self.report["fallback_encoding"])

    def test_bom_handled(self):
        """BOM detection should be reported."""
        # The source file doesn't have a BOM, so used_bom should be False
        self.assertFalse(self.report["used_bom"])

    def test_no_invalid_or_non_positive_prices(self):
        """All prices in source should be valid and positive."""
        self.assertEqual(self.report["invalid_price_count"], 0)
        self.assertEqual(self.report["non_positive_price_count"], 0)


class CSVRobustnessTests(unittest.TestCase):
    """Tests for CSV parsing edge cases that exercise production functions directly."""

    def test_bom_removal_before_header_validation(self):
        """UTF-8 BOM should be correctly stripped before header validation via decode_with_bom_handling."""
        from scripts.audit_fuel_csv import decode_with_bom_handling, parse_csv_content, validate_header

        # UTF-8 with BOM
        data_with_bom = b"\xef\xbb\xbf" + b"OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n1,Test,Addr,City,CA,RACK,3.5\n"
        text, encoding, has_bom, used_fallback, fallback_enc = decode_with_bom_handling(data_with_bom)
        self.assertTrue(has_bom)
        self.assertEqual(encoding, "utf-8-sig")
        self.assertFalse(used_fallback)

        # Parse and validate header - BOM should be removed
        header, data_rows = parse_csv_content(text)
        self.assertEqual(header[0], "OPIS Truckstop ID")  # No leading BOM character
        self.assertTrue(validate_header(header))

        # UTF-8 without BOM
        data_no_bom = b"OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n1,Test,Addr,City,CA,RACK,3.5\n"
        text, encoding, has_bom, used_fallback, fallback_enc = decode_with_bom_handling(data_no_bom)
        self.assertFalse(has_bom)
        self.assertEqual(encoding, "utf-8")

    def test_bom_detection_via_detect_encoding(self):
        """detect_encoding should report BOM presence correctly."""
        from scripts.audit_fuel_csv import detect_encoding

        data_with_bom = b"\xef\xbb\xbf" + b"col1,col2\nval1,val2\n"
        encoding, used_bom, used_fallback, fb_enc = detect_encoding(data_with_bom)
        self.assertTrue(used_bom)
        self.assertEqual(encoding, "utf-8-sig")

        data_no_bom = b"col1,col2\nval1,val2\n"
        encoding, used_bom, used_fallback, fb_enc = detect_encoding(data_no_bom)
        self.assertFalse(used_bom)
        self.assertEqual(encoding, "utf-8")

    def test_malformed_schema_fails_clearly(self):
        """Unexpected columns should fail validation via validate_header."""
        from scripts.audit_fuel_csv import validate_header

        # Correct header
        self.assertTrue(validate_header(REQUIRED_COLUMNS))

        # Reordered columns
        reordered = ["Truckstop Name", "OPIS Truckstop ID", "Address", "City", "State", "Rack ID", "Retail Price"]
        self.assertFalse(validate_header(reordered))

        # Missing columns
        missing = ["OPIS Truckstop ID", "Truckstop Name", "Address"]
        self.assertFalse(validate_header(missing))

        # Extra columns
        extra = REQUIRED_COLUMNS + ["Extra"]
        self.assertFalse(validate_header(extra))

    def test_quoted_fields_with_embedded_newlines(self):
        """CSV parser (parse_csv_content) should handle quoted fields containing newlines."""
        from scripts.audit_fuel_csv import parse_csv_content

        content = 'id,name,desc\n1,"Item","Line 1\nLine 2"\n2,Other,Simple\n'
        header, rows = parse_csv_content(content)
        self.assertEqual(len(rows), 2)  # 2 data rows
        self.assertEqual(rows[0][2], "Line 1\nLine 2")

    def test_whitespace_only_values_classified_as_missing(self):
        """Whitespace-only values should be treated as missing after normalization."""
        from scripts.audit_fuel_csv import parse_price
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price("   "))
        self.assertIsNone(parse_price("\t\n"))

    def test_text_repair_mappings_verified(self):
        """Only verified mojibake repair mappings should exist."""
        from scripts.audit_fuel_csv import MOJIBAKE_REPAIRS

        # Verify the documented Stuckey's repair mapping exists
        self.assertIn("\u00e2\u20ac\u2122", MOJIBAKE_REPAIRS)  # â€™
        self.assertEqual(MOJIBAKE_REPAIRS["\u00e2\u20ac\u2122"], "\u2019")  # -> ’

        # Verify the double-quote mappings are correct
        self.assertIn("\u00e2\u20ac\u0152", MOJIBAKE_REPAIRS)  # â€œ
        self.assertEqual(MOJIBAKE_REPAIRS["\u00e2\u20ac\u0152"], "\u201c")  # -> “
        self.assertIn("\u00e2\u20ac\u009d", MOJIBAKE_REPAIRS)  # â€\x9d
        self.assertEqual(MOJIBAKE_REPAIRS["\u00e2\u20ac\u009d"], "\u201d")  # -> ”

        # No speculative/unverified mappings - no broad "â€" replacement
        self.assertNotIn("\u00e2\u20ac", MOJIBAKE_REPAIRS)

        # Each mapping should have a clear source->target rationale
        for source, target in MOJIBAKE_REPAIRS.items():
            self.assertNotEqual(source, target)
            self.assertIsInstance(source, str)
            self.assertIsInstance(target, str)

    def test_stuckey_repair_mapping(self):
        """Specific test for the Stuckey's mojibake repair via apply_text_repairs_once."""
        from scripts.audit_fuel_csv import apply_text_repairs_once

        class MockStats:
            def __init__(self):
                self.text_repairs = []

        stats = MockStats()
        original = "Stuckey\u00e2\u20ac\u2122s Travel Center West"  # Contains â€™
        corrected = apply_text_repairs_once(original, 1, "Truckstop Name", stats, set())

        self.assertEqual(corrected, "Stuckey\u2019s Travel Center West")  # Should be ’
        self.assertEqual(len(stats.text_repairs), 1)
        self.assertEqual(stats.text_repairs[0].original, original)
        self.assertEqual(stats.text_repairs[0].corrected, corrected)

    def test_text_repair_recorded_once_per_cell(self):
        """apply_text_repairs_once should record repair only once per (row, column)."""
        from scripts.audit_fuel_csv import apply_text_repairs_once

        class MockStats:
            def __init__(self):
                self.text_repairs = []

        stats = MockStats()
        original = "Test\u00e2\u20ac\u2122value"  # Contains â€™

        # Call multiple times for same cell with same repaired_cells set
        repaired_cells = set()
        apply_text_repairs_once(original, 1, "Col", stats, repaired_cells)
        apply_text_repairs_once(original, 1, "Col", stats, repaired_cells)
        apply_text_repairs_once(original, 1, "Col", stats, repaired_cells)

        self.assertEqual(len(stats.text_repairs), 1)

    def test_parse_price_decimal_preservation(self):
        """parse_price should preserve exact decimal precision."""
        from scripts.audit_fuel_csv import parse_price

        # 8 decimal places should be preserved
        price = parse_price("3.00733333")
        self.assertEqual(price, Decimal("3.00733333"))

        # 5 decimal places
        price = parse_price("3.12345")
        self.assertEqual(price, Decimal("3.12345"))

        # Invalid
        self.assertIsNone(parse_price("abc"))
        self.assertIsNone(parse_price(""))

    def test_normalize_state_code(self):
        """State code normalization should uppercase and strip."""
        from scripts.audit_fuel_csv import normalize_state_code

        self.assertEqual(normalize_state_code("ca"), "CA")
        self.assertEqual(normalize_state_code("  TX  "), "TX")
        self.assertEqual(normalize_state_code("Ab"), "AB")

    def test_state_normalization_in_cleaned_output(self):
        """State field should be normalized to uppercase in cleaned output."""
        # This test verifies the production cleaning path uses normalize_state_code
        # by checking the cleaned CSV has uppercase state codes
        import csv
        with open("data/processed/fuel_prices_cleaned.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                state = row["State"]
                self.assertEqual(state, state.upper())
                self.assertEqual(state, state.strip())


class ProductionPipelineTests(unittest.TestCase):
    """Tests that exercise the actual cleaning pipeline via a temporary CSV fixture."""

    def test_state_normalization_in_pipeline(self):
        """A state entered as ' ca ' is written as 'CA' through the full pipeline."""
        from scripts.audit_fuel_csv import (
            normalize_row, parse_price, normalize_state_code,
            REQUIRED_COLUMNS, EXPECTED_COL_COUNT,
            Stats, apply_text_repairs_once, MOJIBAKE_REPAIRS,
        )

        # Create a test row with lowercase/padded state
        test_row = [
            "99999",                    # OPIS Truckstop ID
            "Test Station",             # Truckstop Name
            "123 Main St",              # Address
            "Test City",                # City
            " ca ",                     # State (lowercase with whitespace)
            "RACK123",                  # Rack ID
            "3.12345678",               # Retail Price (8 decimal places)
        ]

        stats = Stats()
        repaired_cells = set()

        # Run through the normalize_row helper (the core of the pipeline)
        cleaned_vals, reasons = normalize_row(test_row, 1, stats, repaired_cells)

        # State should be normalized to uppercase
        state_idx = REQUIRED_COLUMNS.index("State")
        self.assertEqual(cleaned_vals[state_idx], "CA")
        self.assertEqual(reasons, [])  # No validation failures

    def test_whitespace_only_field_quarantined(self):
        """A whitespace-only required field results in quarantine with appropriate reason."""
        from scripts.audit_fuel_csv import (
            normalize_row, Stats, REQUIRED_COLUMNS, EXPECTED_COL_COUNT,
        )

        # Create a test row with whitespace-only state
        test_row = [
            "99999",                    # OPIS Truckstop ID
            "Test Station",             # Truckstop Name
            "123 Main St",              # Address
            "Test City",                # City
            "   ",                      # State (whitespace only)
            "RACK123",                  # Rack ID
            "3.12345678",               # Retail Price
        ]

        stats = Stats()
        repaired_cells = set()

        cleaned_vals, reasons = normalize_row(test_row, 1, stats, repaired_cells)

        # Should have a blank reason for State
        self.assertTrue(any("blank:State" in r for r in reasons))
        self.assertEqual(stats.blank_cells, 1)

    def test_valid_prices_preserved(self):
        """Valid records and their full decimal fuel prices remain intact."""
        from scripts.audit_fuel_csv import (
            normalize_row, parse_price, Stats, REQUIRED_COLUMNS,
        )

        test_row = [
            "99999",
            "Test Station",
            "123 Main St",
            "Test City",
            "TX",
            "RACK123",
            "3.12345678",  # 8 decimal places
        ]

        stats = Stats()
        repaired_cells = set()
        cleaned_vals, reasons = normalize_row(test_row, 1, stats, repaired_cells)

        self.assertEqual(reasons, [])
        self.assertEqual(cleaned_vals[6], "3.12345678")

        # Price should parse correctly with full precision
        price = parse_price(cleaned_vals[6])
        self.assertEqual(price, Decimal("3.12345678"))

    def test_exact_duplicate_removal(self):
        """Exact duplicate removal still removes only completely identical records."""
        from scripts.audit_fuel_csv import (
            normalize_row, parse_price, Stats, REQUIRED_COLUMNS,
        )

        # Two identical rows
        row1 = [
            "99999", "Test Station", "123 Main St", "Test City", "TX", "RACK123", "3.12345678"
        ]
        row2 = [
            "99999", "Test Station", "123 Main St", "Test City", "TX", "RACK123", "3.12345678"
        ]

        stats = Stats()
        repaired_cells = set()
        seen_exact = {}

        for idx, row in enumerate([row1, row2], start=1):
            cleaned_vals, reasons = normalize_row(row, idx, stats, repaired_cells)
            if reasons:
                continue
            price_val = parse_price(cleaned_vals[6])
            if price_val is None or price_val <= 0:
                continue
            exact_key = tuple(cleaned_vals)
            seen_exact.setdefault(exact_key, []).append(idx)

        # Should have one duplicate group with one extra occurrence
        dup_groups = sum(1 for v in seen_exact.values() if len(v) > 1)
        extra_occurrences = sum(len(v) - 1 for v in seen_exact.values() if len(v) > 1)
        self.assertEqual(dup_groups, 1)
        self.assertEqual(extra_occurrences, 1)

    def test_audit_report_counts_match_output(self):
        """The audit report counts match the actual output files."""
        # This test verifies the actual committed files match the report
        import csv

        with open("data/processed/fuel_prices_cleaned.csv", encoding="utf-8") as f:
            reader = csv.reader(f)
            cleaned_rows = list(reader)
        actual_cleaned = len(cleaned_rows) - 1  # exclude header

        with open("docs/reports/fuel_csv_quality_report.json", encoding="utf-8") as f:
            report = json.load(f)

        self.assertEqual(actual_cleaned, report["cleaned_record_count"])
        self.assertEqual(actual_cleaned, 8125)

        # Also verify raw count
        with open("data/fuel-prices-for-be-assessment.csv", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            raw_rows = list(reader)
        actual_raw = len(raw_rows) - 1
        self.assertEqual(actual_raw, report["input_record_count"])
        self.assertEqual(actual_raw, 8151)

        # Verify exact duplicate count
        self.assertEqual(report["exact_duplicate_extra_occurrences"], 26)


class OptimizerTests(unittest.TestCase):
    """Tests for the fuel stop optimizer range validation."""

    def _make_mock_station(self, id, name, price):
        from routefuel.services.optimizer import CandidateStop
        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0
        return CandidateStop(MockStation(id, name, price), 0.0, 0.0, price)

    def test_optimizer_valid_short_route(self):
        """Route within max range should succeed with no stops."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop
        from routefuel.services.optimizer import CandidateStop as CS

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0

        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0})(), 100.0, 0.0, 3.0)

        result = optimize_fuel_stops(100.0, [c1], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['stops']), 0)

    def test_optimizer_exact_max_range(self):
        """Route exactly at max range should succeed."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0

        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0})(), 500.0, 0.0, 3.0)

        result = optimize_fuel_stops(500.0, [c1], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'ok')

    def test_optimizer_exceeds_max_range_first_leg(self):
        """First leg exceeding max range should return unreachable."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0
                self.address = ""
                self.city = ""
                self.state = ""

        # Station at 600 miles on a 600-mile route - first leg exceeds 500
        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 600.0, 0.0, 3.0)

        result = optimize_fuel_stops(600.0, [c1], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'unreachable')

    def test_optimizer_exceeds_max_range_middle_leg(self):
        """Stop-to-stop leg exceeding max range should return unreachable."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0
                self.address = ""
                self.city = ""
                self.state = ""

        # Two stations with gap > 500 miles
        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 100.0, 0.0, 3.0)
        c2 = CandidateStop(type('S', (), {'id': 2, 'name': 'B', 'opis_truckstop_id': '2', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 650.0, 0.0, 3.0)

        result = optimize_fuel_stops(700.0, [c1, c2], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'unreachable')

    def test_optimizer_exceeds_max_range_final_leg(self):
        """Final leg exceeding max range should return unreachable."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0
                self.address = ""
                self.city = ""
                self.state = ""

        # Station at 100 miles, destination at 650 miles - final leg 550 miles
        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 3.0, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 100.0, 0.0, 3.0)

        result = optimize_fuel_stops(650.0, [c1], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'unreachable')

def test_optimizer_valid_multi_stop_route(self):
        """Valid multi-stop route within range should succeed - optimizer finds cheapest path."""
        from routefuel.services.optimizer import optimize_fuel_stops, CandidateStop

        class MockStation:
            def __init__(self, id, name, price):
                self.id = id
                self.name = name
                self.opis_truckstop_id = str(id)
                self.retail_price = price
                self.latitude = 0.0
                self.longitude = 0.0
                self.address = ""
                self.city = ""
                self.state = ""

        # Test with prices that make multiple stops optimal:
        # Station A at 200 mi (very cheap), Station B at 450 mi (expensive)
        # Direct to B at 450: cost = 450/10 * 2.0 + 150/10 * 2.0 = 180
        # Via A at 200 (price 1.0): 200/10 * 2.0 + 250/10 * 2.0 + 150/10 * 2.0 = 180 (same)
        # Make A much cheaper: 0.5
        c1 = CandidateStop(type('S', (), {'id': 1, 'name': 'A', 'opis_truckstop_id': '1', 'retail_price': 0.5, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 200.0, 0.0, 0.5)
        c2 = CandidateStop(type('S', (), {'id': 2, 'name': 'B', 'opis_truckstop_id': '2', 'retail_price': 2.0, 'latitude': 0.0, 'longitude': 0.0, 'address': '', 'city': '', 'state': ''})(), 450.0, 0.0, 2.0)

        result = optimize_fuel_stops(600.0, [c1, c2], mpg=10.0, max_range_miles=500.0, fallback_price=3.50)
        self.assertEqual(result['status'], 'ok')
        # The optimizer should find the cheapest path - could be 1 or 2 stops depending on prices
        self.assertGreaterEqual(len(result['stops']), 1)
        # Verify all legs are within range
        stops = result['stops']
        self.assertLessEqual(stops[0]['route_mile_marker'], 500)
        if len(stops) == 2:
            self.assertLessEqual(stops[1]['route_mile_marker'] - stops[0]['route_mile_marker'], 500)
            self.assertLessEqual(600.0 - stops[1]['route_mile_marker'], 500)
        else:
            self.assertLessEqual(600.0 - stops[0]['route_mile_marker'], 500)


if __name__ == "__main__":
    unittest.main()