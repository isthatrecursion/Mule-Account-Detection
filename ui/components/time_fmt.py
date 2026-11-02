"""Convert aware API timestamps without inventing a timezone for missing data."""

from datetime import datetime
from zoneinfo import ZoneInfo


def format_time(value: datetime | str | None, timezone: str = "UTC") -> str:
    if value is None:
        return "Not supplied"
    try:
        stamp = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return "Unknown timezone"
        return (
            stamp.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S %z")
            + " ["
            + timezone
            + "]"
        )
    except (ValueError, KeyError, TypeError):
        return "Invalid timestamp"
