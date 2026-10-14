# Fuel CSV Quality Report

- Source: data/fuel-prices-for-be-assessment.csv
- Input record count: 8151
- Cleaned record count: 8125
- Quarantined record count: 0
- Schema valid: True
- Encoding: utf-8 (BOM: False; fallback used: False; fallback: None)
- Delimiter: ,
- Column count: 7
- Header: ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID', 'Retail Price']
- Source SHA-256: c704371f141ded9c54df6c32d488a0ba2ceb589f88c936c967daa5330e0cd241
- Blank cells: 0
- Whitespace cells normalized: 1356
- Malformed rows: 0
- Invalid price count: 0
- Non-positive price count: 0
- Text repairs: 1
- Exact duplicate groups: 15
- Exact duplicate extra occurrences: 26
- Repeated station ID groups: 678
- Repeated station ID extra occurrences: 1413
- US records (cleaned): 7505
- CA records (cleaned): 620
- Unknown geo records (cleaned): 0

## Price statistics

### Raw dataset (all source rows with a parseable positive price)
- Count: 8151
- Min: 2.68733333
- Max: 6.399
- Mean: 3.498973929009937430990062569

### Cleaned dataset (rows written to fuel_prices_cleaned.csv)
- Count: 8125
- Min: 2.68733333
- Max: 6.399
- Mean: 3.498908614813538461538461538

## Notes
- Original source CSV preserved unchanged.
- Station IDs and Rack IDs kept as strings.
- Only verified completely identical duplicate records removed from cleaned output.
- Text repairs limited to documented mojibake sequences.
- Quarantined rows include source row numbers and reasons.