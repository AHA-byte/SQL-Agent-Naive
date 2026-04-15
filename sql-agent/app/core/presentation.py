from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "nan"}:
        return True
    return False


def _friendly_label(key: str) -> str:
    key = (key or "").replace("_", " ").strip()
    if not key:
        return "Field"
    return " ".join(part.upper() if part.upper() in {"ID", "SOW", "QBCC", "SQL"} else part.capitalize() for part in key.split())


def _looks_like_money(label: str) -> bool:
    lower = (label or "").lower()
    return any(token in lower for token in ["amount", "total", "balance", "cost", "price", "premium", "sow", "purch"])


def _format_value(label: str, value) -> str:
    if _is_empty(value):
        return "Not available"

    if isinstance(value, (int, float, Decimal)):
        if _looks_like_money(label):
            return f"${float(value):,.2f}"
        if isinstance(value, float):
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:,}"

    if isinstance(value, str):
        value = value.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value[:19], fmt)
                return dt.strftime("%d %b %Y")
            except ValueError:
                pass
    return str(value)


def _is_id_key(key: str) -> bool:
    lower = (key or "").lower().strip()
    return lower == "id" or lower.endswith("id") or lower.endswith(" id") or lower.endswith("_id")


def _detect_response_type(result: dict) -> str:
    meta = result.get("meta") or {}
    intent = (meta.get("intent") or "").upper()
    jobs = result.get("jobs") or []
    rows = result.get("rows") or []

    if jobs:
        return "RELATIONSHIP"
    if intent in {"RELATIONSHIP"}:
        return "RELATIONSHIP"
    if intent in {"AGGREGATION", "TREND"}:
        return "AGGREGATE"
    if intent in {"DOMAIN_SPECIFIC"}:
        return "BUSINESS"
    if rows:
        first = rows[0]
        numeric_count = sum(1 for value in first.values() if isinstance(value, (int, float, Decimal)))
        if numeric_count >= 2:
            return "AGGREGATE"
    return "LIST"


def _summary_for_type(response_type: str, shown_count: int) -> str:
    if shown_count == 0:
        return "I could not find matching business data for that request."
    if response_type == "RELATIONSHIP":
        return f"Here are the top {shown_count} grouped relationship results."
    if response_type == "AGGREGATE":
        return f"Here is a summary of the top {shown_count} metric rows."
    if response_type == "BUSINESS":
        return f"Here are the top {shown_count} business results."
    return f"Here are the top {shown_count} records."


def _format_rows(rows: list[dict], max_items: int) -> list[str]:
    blocks: list[str] = []
    for idx, row in enumerate(rows[:max_items], 1):
        lines = [f"{idx}."]
        shown = 0
        for key, value in row.items():
            if _is_id_key(key):
                continue
            label = _friendly_label(key)
            lines.append(f"{label}: {_format_value(key, value)}")
            shown += 1
            if shown >= 5:
                break
        blocks.append("\n".join(lines))
    return blocks


def _format_grouped_jobs(grouped_jobs: list[dict], max_items: int) -> list[str]:
    blocks: list[str] = []
    for idx, item in enumerate(grouped_jobs[:max_items], 1):
        lines = [f"{idx}. Job: {item.get('jobNumber', 'Unknown')}"]
        for key in ("allocations", "reminders", "workOrders"):
            values = item.get(key) or []
            if values:
                lines.append(f"{_friendly_label(key)}: {', '.join(str(v) for v in values[:5])}")
        blocks.append("\n".join(lines))
    return blocks


def _optional_insight(response_type: str, rows: list[dict]) -> str | None:
    if not rows:
        return None
    if response_type == "AGGREGATE":
        first = rows[0]
        label_key = next((k for k in first.keys() if isinstance(first.get(k), str)), None)
        metric_key = next((k for k in first.keys() if isinstance(first.get(k), (int, float, Decimal))), None)
        if label_key and metric_key:
            return f"Top contributor: {_format_value(label_key, first[label_key])} ({_format_value(metric_key, first[metric_key])})."
    if response_type == "LIST":
        first = rows[0]
        status_key = next((k for k in first.keys() if "status" in k.lower()), None)
        if status_key:
            counts = Counter(str(row.get(status_key)) for row in rows if row.get(status_key) is not None)
            if counts:
                status, amount = counts.most_common(1)[0]
                return f"Most common status in these results: {status} ({amount})."
    return None


def build_response_view(result: dict, max_items: int = 5) -> dict:
    status = result.get("status")
    if status != "success":
        message = (result.get("error") or result.get("message") or "I could not complete that request right now.").strip()
        return {
            "summary": message,
            "rows": [],
            "insight": None,
            "response_type": "ERROR",
        }

    rows = result.get("rows") or []
    grouped_jobs = result.get("jobs") or []
    response_type = _detect_response_type(result)

    shown_count = min(max_items, len(grouped_jobs) if grouped_jobs else len(rows))
    summary = _summary_for_type(response_type, shown_count)

    if grouped_jobs:
        formatted_rows = _format_grouped_jobs(grouped_jobs, max_items=max_items)
    else:
        formatted_rows = _format_rows(rows, max_items=max_items)

    insight = _optional_insight(response_type, rows)
    return {
        "summary": summary,
        "rows": formatted_rows,
        "insight": insight,
        "response_type": response_type,
    }