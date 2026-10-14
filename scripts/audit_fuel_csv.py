#!/usr/bin/env python3
"""
Audit and clean the fuel-prices CSV file.

This script:
- Preserves the original source CSV unchanged.
- Computes SHA-256 hash of the original file.
- Handles UTF-8 BOM and detects encoding failures explicitly.
- Validates header, delimiter, and column count; fails on unexpected schemas.
- Identifies missing values, whitespace-only fields, malformed rows, invalid prices.
- Keeps station IDs and rack IDs as strings to preserve leading zeros.
- Normalizes leading/trailing whitespace in textual fields and normalizes state codes.
- Applies only documented, verified text repairs (mojibake corrections).
- Validates retail prices using Decimal-safe parsing.
- Reports exact duplicate rows and repeated station IDs separately.
- Removes only verified completely identical duplicate records from cleaned output.
- Classifies US states/DC vs Canadian provinces vs unknown codes.
- Quarantines malformed/unprocessable rows with source row numbers and reasons.
- Produces deterministic UTF-8 output compatible across Windows and Unix.

Outputs:
- data/processed/fuel_prices_cleaned.csv
- data/processed/fuel_prices_quarantine.csv
- docs/reports/fuel_csv_quality_report.md
- docs/reports/fuel_csv_quality_report.json
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_COLUMNS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]
EXPECTED_COL_COUNT = len(REQUIRED_COLUMNS)

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}
CA_PROVINCE_CODES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
TEXT_COLUMNS = ["Truckstop Name", "Address", "City", "State"]

# Verified mojibake repair mappings (source -> target)
# Only retain mappings that represent verified source sequences and intended Unicode characters.
# When UTF-8 is misread as Windows-1252/Latin-1:
# - ’ (U+2019) -> bytes E2 80 99 -> misread as â (E2), € (80), ™ (99) -> â€™
# - “ (U+201C) -> bytes E2 80 9C -> misread as â (E2), € (80), œ (9C) -> â€œ
# - ” (U+201D) -> bytes E2 80 9D -> misread as â (E2), € (80), \x9D (9D) -> â€\x9d
# Do NOT include broad replacements like "â€" -> "”" that can corrupt unverified text.
MOJIBAKE_REPAIRS = {
    "\u00e2\u20ac\u2122": "\u2019",  # â€™ -> ’ (right single quotation mark)
    "\u00e2\u20ac\u0152": "\u201c",  # â€œ -> “ (left double quotation mark)
    "\u00e2\u20ac\u009d": "\u201d",  # â€\x9d -> ” (right double quotation mark)
    # Latin-1/Windows-1252 mojibake from UTF-8 accented chars
    "\u00c3\u00a9": "\u00e9",         # Ã© -> é
    "\u00c3\u00a8": "\u00e8",         # Ã¨ -> è
    "\u00c3\u00b4": "\u00f4",         # Ã´ -> ô
    "\u00c3\u00a7": "\u00e7",         # Ã§ -> ç
    "\u00c3\u00b1": "\u00f1",         # Ã± -> ñ
}


@dataclass
class TextRepair:
    row_number: int
    column: str
    original: str
    corrected: str
    reason: str


@dataclass
class Stats:
    input_record_count: int = 0
    cleaned_record_count: int = 0
    quarantined_record_count: int = 0
    schema_valid: bool = True
    encoding: str = "utf-8"
    used_bom: bool = False
    used_fallback_encoding: bool = False
    fallback_encoding: Optional[str] = None
    delimiter: str = ","
    column_count: int = 0
    header: List[str] = field(default_factory=list)
    blank_cells: int = 0
    whitespace_cells_normalized: int = 0
    malformed_rows: int = 0
    invalid_price_count: int = 0
    non_positive_price_count: int = 0
    text_repairs: List[TextRepair] = field(default_factory=list)
    exact_duplicate_groups: int = 0
    exact_duplicate_extra_occurrences: int = 0
    repeated_station_id_groups: int = 0
    repeated_station_id_extra_occurrences: int = 0
    us_records: int = 0
    ca_records: int = 0
    unknown_geo_records: int = 0
    # Raw dataset statistics (all source rows with parseable positive price)
    raw_min_price: Optional[Decimal] = None
    raw_max_price: Optional[Decimal] = None
    raw_mean_price: Optional[Decimal] = None
    raw_record_count: int = 0
    # Cleaned dataset statistics (rows written to cleaned CSV)
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    mean_price: Optional[Decimal] = None
    quarantined_rows: List[Dict[str, Any]] = field(default_factory=list)


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_encoding(data: bytes) -> Tuple[str, bool, bool, Optional[str]]:
    """
    Detect file encoding. Check for UTF-8 BOM first.
    If BOM present, use utf-8-sig which removes it.
    If no BOM, try plain UTF-8.
    If UTF-8 fails, try latin-1 as a documented fallback.
    Never silently decode with a lossy strategy.
    """
    has_bom = data.startswith(b"\xef\xbb\xbf")
    if has_bom:
        # BOM present - use utf-8-sig which handles and removes it
        try:
            data.decode("utf-8-sig")
            return "utf-8-sig", True, False, None
        except UnicodeDecodeError:
            pass  # Fall through to fallback attempts

    # No BOM - try plain UTF-8
    try:
        data.decode("utf-8")
        return "utf-8", False, False, None
    except UnicodeDecodeError:
        # Documented fallback: latin-1
        try:
            data.decode("latin-1")
            return "latin-1", False, True, "latin-1"
        except Exception as e:
            raise UnicodeError(f"Failed to decode file: {e}") from e


def apply_text_repairs_once(s: str, row_num: int, col: str, stats: Stats, repaired_cells: set) -> str:
    """
    Apply text repairs, recording only once per cell.
    This function is module-level so it can be imported and tested independently.
    """
    if not s:
        return s
    original = s
    corrected = s
    for source, target in MOJIBAKE_REPAIRS.items():
        if source in corrected:
            corrected = corrected.replace(source, target)
    if corrected != original:
        cell_key = (row_num, col)
        if cell_key not in repaired_cells:
            repaired_cells.add(cell_key)
            stats.text_repairs.append(
                TextRepair(
                    row_number=row_num,
                    column=col,
                    original=original,
                    corrected=corrected,
                    reason="Documented mojibake repair",
                )
            )
    return corrected


def normalize_state_code(s: str) -> str:
    """Normalize state code to uppercase, stripped."""
    return s.upper().strip()


def parse_price(s: str) -> Optional[Decimal]:
    """Parse a price string to Decimal, returning None on failure."""
    try:
        return Decimal(s.strip())
    except (InvalidOperation, ValueError):
        return None


def normalize_row(row_padded: List[str], idx: int, stats: Stats, repaired_cells: set, count_whitespace: bool = True) -> Tuple[List[str], List[str]]:
    """
    Normalize a single row for cleaning.
    Returns (cleaned_vals, reasons) where cleaned_vals is the normalized row
    and reasons is a list of validation failure reasons.
    """
    reasons: List[str] = []
    cleaned_vals = [""] * EXPECTED_COL_COUNT
    is_quar = False

    for j, col in enumerate(REQUIRED_COLUMNS):
        raw = row_padded[j] if j < len(row_padded) else ""

        # Check for blank or whitespace-only after stripping
        stripped = raw.strip()
        if not stripped:
            stats.blank_cells += 1
            reasons.append(f"blank:{col}")
            cleaned_vals[j] = ""
            continue

        # Track whitespace normalization (only in first pass)
        if count_whitespace and raw != stripped:
            stats.whitespace_cells_normalized += 1

        norm = stripped
        if col in TEXT_COLUMNS:
            repaired = apply_text_repairs_once(norm, idx, col, stats, repaired_cells)
            # Apply state normalization for the State field
            if col == "State":
                norm = normalize_state_code(repaired)
            else:
                norm = repaired
            cleaned_vals[j] = norm
        else:
            cleaned_vals[j] = norm

    return cleaned_vals, reasons


def validate_header(header: List[str]) -> bool:
    """
    Validate that the CSV header matches the expected schema exactly.
    Returns True if valid, False otherwise.
    """
    return list(header) == REQUIRED_COLUMNS


def parse_csv_content(text: str, delimiter: str = ",") -> Tuple[List[str], List[List[str]]]:
    """
    Parse CSV content using csv.reader on a StringIO to handle quoted newlines correctly.
    Returns (header, data_rows).
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("Empty CSV")
    data_rows = list(reader)
    return header, data_rows


def decode_with_bom_handling(raw_bytes: bytes) -> Tuple[str, str, bool, bool, Optional[str]]:
    """
    Decode bytes with proper BOM handling.
    Returns (text, encoding_used, has_bom, used_fallback, fallback_encoding).
    """
    encoding, used_bom, used_fallback, fallback_enc = detect_encoding(raw_bytes)
    if encoding == "utf-8-sig":
        text = raw_bytes.decode("utf-8-sig")
    elif encoding == "latin-1":
        text = raw_bytes.decode("latin-1")
    else:
        text = raw_bytes.decode("utf-8")
    return text, encoding, used_bom, used_fallback, fallback_enc


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    source_path = base_dir / "data" / "fuel-prices-for-be-assessment.csv"
    # Use project-relative path for reports (portable across machines)
    source_rel_path = "data/fuel-prices-for-be-assessment.csv"
    cleaned_dir = base_dir / "data" / "processed"
    reports_dir = base_dir / "docs" / "reports"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    cleaned_path = cleaned_dir / "fuel_prices_cleaned.csv"
    quarantine_path = cleaned_dir / "fuel_prices_quarantine.csv"
    report_md_path = reports_dir / "fuel_csv_quality_report.md"
    report_json_path = reports_dir / "fuel_csv_quality_report.json"

    if not source_path.exists():
        raise FileNotFoundError(f"Source CSV not found: {source_path}")

    stats = Stats()
    source_sha256 = compute_sha256(source_path)
    raw_bytes = source_path.read_bytes()
    text, encoding, used_bom, used_fallback, fallback_enc = decode_with_bom_handling(raw_bytes)
    stats.encoding = encoding
    stats.used_bom = used_bom
    stats.used_fallback_encoding = used_fallback
    stats.fallback_encoding = fallback_enc

    # Detect delimiter from a sample
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","
    stats.delimiter = delimiter

    # Parse CSV using csv.reader on a StringIO to handle quoted newlines correctly.
    # Do NOT split into physical lines first, as that breaks quoted fields with embedded newlines.
    header, data_rows = parse_csv_content(text, delimiter)
    if not validate_header(header):
        stats.schema_valid = False
        raise ValueError(
            f"CSV schema mismatch. Expected: {REQUIRED_COLUMNS}, Got: {header}"
        )

    stats.header = header
    stats.column_count = len(header)
    stats.input_record_count = len(data_rows)

    qheader = ["source_row_number", "reason"] + header
    quarantine_rows_out = []
    seen_exact: Dict[Tuple[str, ...], List[int]] = {}
    station_id_counts: Dict[str, int] = {}

    # Collect raw prices for raw dataset statistics (all valid positive prices)
    raw_prices: List[Decimal] = []
    # Collect cleaned prices for cleaned dataset statistics (after normalization, dedup)
    cleaned_prices: List[Decimal] = []

    # Track written exact duplicate keys to avoid re-processing
    written_exact_keys: set = set()
    # Track which (row_idx, column) pairs have had text repairs recorded
    repaired_cells: set = set()

    for idx, row in enumerate(data_rows, start=2):
        reasons: List[str] = []

        # Check column count
        if len(row) != EXPECTED_COL_COUNT:
            reasons.append(f"wrong_column_count:{len(row)}_expected_{EXPECTED_COL_COUNT}")

        # Pad or truncate row to expected column count
        if len(row) < EXPECTED_COL_COUNT:
            row_padded = list(row) + [""] * (EXPECTED_COL_COUNT - len(row))
        else:
            row_padded = list(row[:EXPECTED_COL_COUNT])

        # Normalize row using shared helper
        cleaned_vals, norm_reasons = normalize_row(row_padded, idx, stats, repaired_cells)
        reasons.extend(norm_reasons)

        # Collect raw price for raw statistics (from original row, before cleaning)
        raw_price = parse_price(row_padded[6] if len(row_padded) > 6 else "")
        if raw_price is not None and raw_price > 0:
            raw_prices.append(raw_price)

        # Validate cleaned price
        price_raw = cleaned_vals[6]
        price_val = parse_price(price_raw)
        if price_val is None:
            stats.invalid_price_count += 1
            reasons.append("invalid_price")
        elif price_val <= 0:
            stats.non_positive_price_count += 1
            reasons.append("non_positive_price")

        if reasons:
            stats.quarantined_record_count += 1
            stats.malformed_rows += 1
            quarantine_rows_out.append([str(idx), ";".join(sorted(set(reasons)))] + row_padded)
            stats.quarantined_rows.append({
                "source_row_number": idx,
                "reasons": sorted(set(reasons)),
                "raw_values": row_padded,
            })
            continue

        # Row is valid for cleaning
        station_id = cleaned_vals[0]
        station_id_counts[station_id] = station_id_counts.get(station_id, 0) + 1
        exact_key = tuple(cleaned_vals)
        seen_exact.setdefault(exact_key, []).append(idx)

    # Analyze duplicates after seeing all rows
    eg = ee = 0
    for k, v in seen_exact.items():
        if len(v) > 1:
            eg += 1
            ee += (len(v) - 1)
    stats.exact_duplicate_groups = eg
    stats.exact_duplicate_extra_occurrences = ee

    rg = re = 0
    for sid, c in station_id_counts.items():
        if c > 1:
            rg += 1
            re += (c - 1)
    stats.repeated_station_id_groups = rg
    stats.repeated_station_id_extra_occurrences = re

    # Write quarantine CSV
    with quarantine_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(qheader)
        for qr in quarantine_rows_out:
            w.writerow(qr)

    # Second pass: write cleaned CSV and collect cleaned prices
    with cleaned_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(REQUIRED_COLUMNS)
        for idx, row in enumerate(data_rows, start=2):
            # Skip rows that were quarantined (wrong column count, etc.)
            if len(row) != EXPECTED_COL_COUNT:
                continue
            if len(row) < EXPECTED_COL_COUNT:
                row_padded = list(row) + [""] * (EXPECTED_COL_COUNT - len(row))
            else:
                row_padded = list(row[:EXPECTED_COL_COUNT])

            # Normalize row using shared helper
            cleaned_vals, norm_reasons = normalize_row(row_padded, idx, stats, repaired_cells, count_whitespace=False)
            if norm_reasons:
                # Row has blank/invalid/non-positive price - skip
                continue

            price_val = parse_price(cleaned_vals[6])
            if price_val is None or price_val <= 0:
                continue

            exact_key = tuple(cleaned_vals)
            if exact_key in written_exact_keys:
                continue
            written_exact_keys.add(exact_key)

            # Classify geography - state is already normalized in cleaned_vals
            state = cleaned_vals[4]
            if state in US_STATE_CODES:
                stats.us_records += 1
            elif state in CA_PROVINCE_CODES:
                stats.ca_records += 1
            else:
                stats.unknown_geo_records += 1

            w.writerow(cleaned_vals)
            stats.cleaned_record_count += 1
            cleaned_prices.append(price_val)

    # Compute statistics using Decimal arithmetic
    if raw_prices:
        stats.raw_record_count = len(raw_prices)
        stats.raw_min_price = min(raw_prices)
        stats.raw_max_price = max(raw_prices)
        stats.raw_mean_price = sum(raw_prices) / Decimal(len(raw_prices))

    if cleaned_prices:
        stats.min_price = min(cleaned_prices)
        stats.max_price = max(cleaned_prices)
        stats.mean_price = sum(cleaned_prices) / Decimal(len(cleaned_prices))

    # Generate Markdown report
    report_md = []
    report_md.append("# Fuel CSV Quality Report")
    report_md.append("")
    report_md.append(f"- Source: {source_rel_path}")
    report_md.append(f"- Input record count: {stats.input_record_count}")
    report_md.append(f"- Cleaned record count: {stats.cleaned_record_count}")
    report_md.append(f"- Quarantined record count: {stats.quarantined_record_count}")
    report_md.append(f"- Schema valid: {stats.schema_valid}")
    report_md.append(
        f"- Encoding: {stats.encoding} (BOM: {stats.used_bom}; "
        f"fallback used: {stats.used_fallback_encoding}; fallback: {stats.fallback_encoding})"
    )
    report_md.append(f"- Delimiter: {stats.delimiter}")
    report_md.append(f"- Column count: {stats.column_count}")
    report_md.append(f"- Header: {stats.header}")
    report_md.append(f"- Source SHA-256: {source_sha256}")
    report_md.append(f"- Blank cells: {stats.blank_cells}")
    report_md.append(f"- Whitespace cells normalized: {stats.whitespace_cells_normalized}")
    report_md.append(f"- Malformed rows: {stats.malformed_rows}")
    report_md.append(f"- Invalid price count: {stats.invalid_price_count}")
    report_md.append(f"- Non-positive price count: {stats.non_positive_price_count}")
    report_md.append(f"- Text repairs: {len(stats.text_repairs)}")
    report_md.append(f"- Exact duplicate groups: {stats.exact_duplicate_groups}")
    report_md.append(f"- Exact duplicate extra occurrences: {stats.exact_duplicate_extra_occurrences}")
    report_md.append(f"- Repeated station ID groups: {stats.repeated_station_id_groups}")
    report_md.append(f"- Repeated station ID extra occurrences: {stats.repeated_station_id_extra_occurrences}")
    report_md.append(f"- US records (cleaned): {stats.us_records}")
    report_md.append(f"- CA records (cleaned): {stats.ca_records}")
    report_md.append(f"- Unknown geo records (cleaned): {stats.unknown_geo_records}")
    report_md.append("")
    report_md.append("## Price statistics")
    report_md.append("")
    report_md.append("### Raw dataset (all source rows with a parseable positive price)")
    report_md.append(f"- Count: {stats.raw_record_count}")
    report_md.append(f"- Min: {stats.raw_min_price}")
    report_md.append(f"- Max: {stats.raw_max_price}")
    report_md.append(f"- Mean: {stats.raw_mean_price}")
    report_md.append("")
    report_md.append("### Cleaned dataset (rows written to fuel_prices_cleaned.csv)")
    report_md.append(f"- Count: {stats.cleaned_record_count}")
    report_md.append(f"- Min: {stats.min_price}")
    report_md.append(f"- Max: {stats.max_price}")
    report_md.append(f"- Mean: {stats.mean_price}")
    report_md.append("")
    report_md.append("## Notes")
    report_md.append("- Original source CSV preserved unchanged.")
    report_md.append("- Station IDs and Rack IDs kept as strings.")
    report_md.append("- Only verified completely identical duplicate records removed from cleaned output.")
    report_md.append("- Text repairs limited to documented mojibake sequences.")
    report_md.append("- Quarantined rows include source row numbers and reasons.")
    Path(report_md_path).write_text("\n".join(report_md), encoding="utf-8")

    # Generate JSON report (convert Decimal to string for exact representation)
    rep = asdict(stats)
    rep["source_sha256"] = source_sha256
    rep["text_repairs"] = [asdict(t) for t in stats.text_repairs]
    # Convert Decimal fields to string for exact JSON representation
    for key in [
        "raw_min_price", "raw_max_price", "raw_mean_price",
        "min_price", "max_price", "mean_price",
    ]:
        if rep[key] is not None:
            rep[key] = str(rep[key])
    Path(report_json_path).write_text(json.dumps(rep, indent=2), encoding="utf-8")

    print("Done")


if __name__ == "__main__":
    main()