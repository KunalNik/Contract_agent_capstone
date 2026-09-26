from neo4j.time import Date, DateTime
import re
from datetime import datetime
from typing import Optional


def convert_neo4j_date(value):
    """Convert Neo4j temporal values to ISO strings (zero-padded, sortable)."""
    if isinstance(value, dict):
        return {k: convert_neo4j_date(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [convert_neo4j_date(item) for item in value]
    elif isinstance(value, (Date, DateTime)):
        return value.iso_format()
    return value


def to_json_safe(value):
    """Make Neo4j query results JSON-friendly for API responses.

    FastAPI serialises neo4j.time objects as their private fields
    (``{'_DateTime__date': ...}``); convert them to ISO strings instead.
    """
    return convert_neo4j_date(value)


def _valid_iso(year, month, day) -> Optional[str]:
    """Return YYYY-MM-DD only for real calendar dates (Neo4j date() rejects others)."""
    try:
        return datetime(int(year), int(month), int(day)).strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def parse_date_to_iso(date_str: str) -> Optional[str]:
    """
    Parse various date formats into ISO 8601 (YYYY-MM-DD) for Neo4j compatibility.
    Handles:
    - October 16, 2023
    - 16 October 2023 / 16th October 2023
    - 2023-10-16
    - 10/16/2023 (MM/DD) and 16/10/2023 (DD/MM when unambiguous)
    Returns None for anything that is not a real calendar date, so a bad LLM
    value can never make the whole contract insert fail.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.strip()

    # ISO format first
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match:
        return _valid_iso(*match.groups())

    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }

    # Format: October 16, 2023 or Oct 16, 2023
    match = re.search(r'([a-zA-Z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,\s]+\s*(\d{4})', date_str)
    if match:
        month_name, day, year = match.groups()
        month_idx = months.get(month_name.lower())
        if month_idx:
            result = _valid_iso(year, month_idx, day)
            if result:
                return result

    # Format: 16 October 2023, 16th of October, 2023
    match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-zA-Z]+)\.?,?\s+(\d{4})', date_str)
    if match:
        day, month_name, year = match.groups()
        month_idx = months.get(month_name.lower())
        if month_idx:
            result = _valid_iso(year, month_idx, day)
            if result:
                return result

    # Format: 10/16/2023 (US) or 16/10/2023 when the first part cannot be a month
    match = re.search(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', date_str)
    if match:
        a, b, y = match.groups()
        return _valid_iso(y, a, b) or _valid_iso(y, b, a)

    # Final fallback: generic ISO datetime parse
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    return None
