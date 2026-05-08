"""
Data Validator - Ensures query results are real and valid.
"""

from typing import Any


def validate_query_result(raw_data: list, sql_query: str) -> dict:
    """
    Validate that query results are real and properly executed.
    
    Returns dict with validation status and any warnings.
    """
    result = {
        "is_valid": True,
        "warnings": [],
        "row_count": 0,
        "has_data": False,
    }
    
    if not raw_data:
        result["warnings"].append("Query returned no rows")
        result["is_valid"] = True  # Valid but empty
        return result
    
    result["row_count"] = len(raw_data)
    result["has_data"] = True
    
    # Check for suspicious patterns
    first_row = raw_data[0]
    
    # Check if data looks like placeholder values
    suspicious_values = ["N/A", "null", "undefined", "unknown", "TBD"]
    for val in first_row.values():
        if isinstance(val, str) and val.lower() in suspicious_values:
            result["warnings"].append(f"Contains placeholder value: {val}")
    
    # Check for all identical rows (might indicate fake data)
    if len(raw_data) > 1:
        first_row_str = str(list(first_row.values()))
        identical_count = sum(1 for row in raw_data if str(list(row.values())) == first_row_str)
        if identical_count == len(raw_data) and len(raw_data) > 5:
            result["warnings"].append("All rows appear identical - possible data issue")
    
    return result


def detect_data_anomalies(data: list, column: str = None) -> list:
    """
    Detect potential anomalies in the data.
    
    Returns list of anomaly descriptions.
    """
    if not data or len(data) < 2:
        return []
    
    anomalies = []
    
    # Check for high null percentage in any column
    null_counts = {}
    for row in data:
        for key, val in row.items():
            if val is None:
                null_counts[key] = null_counts.get(key, 0) + 1
    
    for col, count in null_counts.items():
        pct = (count / len(data)) * 100
        if pct > 50:
            anomalies.append(f"Column '{col}' has {pct:.1f}% null values")
    
    # Check for duplicate key values if there's an ID column
    id_columns = [k for k in data[0].keys() if "id" in k.lower()]
    for id_col in id_columns:
        ids = [row.get(id_col) for row in data if row.get(id_col)]
        if len(ids) != len(set(ids)):
            duplicates = len(ids) - len(set(ids))
            anomalies.append(f"Column '{id_col}' has {duplicates} duplicate IDs")
    
    return anomalies


def generate_data_quality_note(raw_data: list) -> str:
    """
    Generate a brief data quality note for the report.
    """
    if not raw_data:
        return "No data available for analysis."
    
    validation = validate_query_result(raw_data, "")
    
    notes = [
        f"Total records: {validation['row_count']}"
    ]
    
    if validation["warnings"]:
        notes.append("Data quality notes:")
        for warning in validation["warnings"]:
            notes.append(f"  - {warning}")
    
    anomalies = detect_data_anomalies(raw_data)
    if anomalies:
        notes.append("Potential issues detected:")
        for anomaly in anomalies[:3]:  # Limit to 3
            notes.append(f"  - {anomaly}")
    
    return " | ".join(notes[:2])  # Return first 2 notes max


def ensure_numeric_column(data: list, column: str) -> list:
    """
    Ensure a column contains numeric values. Convert if needed.
    """
    if not data or column not in data[0]:
        return data
    
    numeric_data = []
    for row in data:
        val = row.get(column)
        if val is None:
            numeric_data.append(row)
            continue
        
        try:
            if isinstance(val, str):
                # Try to convert to float
                cleaned = val.replace(",", "").replace("$", "").replace("%", "")
                row[column] = float(cleaned)
        except (ValueError, AttributeError):
            pass  # Keep original value
        
        numeric_data.append(row)
    
    return numeric_data