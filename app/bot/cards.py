from __future__ import annotations

import math
import re

from botbuilder.core import CardFactory, MessageFactory
from botbuilder.schema import Attachment


_FIELD_PRIORITY = [
    "jobnumber",
    "jobNumber",
    "reminder",
    "remindername",
    "reminderdate",
    "status",
    "customername",
    "address",
    "claim number",
    "claimnumber",
    "sow",
    "qbcc purch",
    "policy number",
    "contract amount",
    "premium amount",
]

_LABEL_OVERRIDES = {
    "jobnumber": "Job Number",
    "claimnumber": "Claim Number",
}


def _friendly_error_message(raw_error: str) -> str:
    message = (raw_error or "").strip()
    lowered = message.lower()
    if not message:
        return "I could not complete that request right now. Please try again."

    if "failed to generate valid sql" in lowered or "is not allowed for table" in lowered:
        return "I could not map that question to valid fields in the current data model. Please rephrase and I can try again."

    if "invalid column name" in lowered:
        return "I could not find one of the requested fields in the database. Please try a slightly simpler version of that question."

    if "incorrect syntax" in lowered or "programmingerror" in lowered:
        return "I could not complete that report due to a query formatting issue. Please try again while I use a safer template."

    return "I could not complete that request right now. Please try again."


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"", "none", "null", "nan"}:
            return True
    return False


def _format_value(value) -> str:
    if _is_empty_value(value):
        return "Not available"
    if isinstance(value, float):
        # Avoid noisy float representations in chat cards.
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _friendly_label(key: str) -> str:
    normalized = key.replace("_", "").replace(" ", "").lower()
    if normalized in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[normalized]

    # Convert camelCase/snake_case and keep known acronyms readable.
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key.replace("_", " ")).strip()
    if not text:
        return "Field"
    words = text.split()
    transformed = []
    for word in words:
        upper = word.upper()
        if upper in {"ID", "SOW", "QBCC", "SQL"}:
            transformed.append(upper)
        else:
            transformed.append(word.capitalize())
    return " ".join(transformed)


def _display_items(row: dict, limit: int = 5) -> list[tuple[str, str]]:
    if not row:
        return []

    ordered_keys: list[str] = []
    row_keys = list(row.keys())
    row_keys_lower = {k.lower(): k for k in row_keys}

    for preferred in _FIELD_PRIORITY:
        if preferred.lower() in row_keys_lower:
            actual_key = row_keys_lower[preferred.lower()]
            if actual_key not in ordered_keys:
                ordered_keys.append(actual_key)

    for key in row_keys:
        lowered = key.lower().strip()
        if key in ordered_keys:
            continue
        if lowered == "id" or lowered.endswith(" id") or lowered.endswith("_id") or lowered.endswith("id"):
            continue
        ordered_keys.append(key)

    items: list[tuple[str, str]] = []
    for key in ordered_keys:
        value = _format_value(row.get(key))
        if value == "Not available" and len(items) >= 2:
            continue
        items.append((_friendly_label(key), value))
        if len(items) >= limit:
            break
    return items


def build_summary_text(result: dict) -> str:
    if result.get("status") != "success":
        return _friendly_error_message(result.get("error") or result.get("message") or "")

    rows = result.get("rows") or []
    row_count = len(rows)

    if row_count == 0:
        return "I ran the query but found no matching rows."

    first = rows[0]
    if "Brand" in first and "Job Count" in first:
        return (
            f"I found {row_count} brand group(s). "
            f"Top brand: {_format_value(first.get('Brand'))} with {_format_value(first.get('Job Count'))} jobs."
        )

    if first_job_number := first.get("jobNumber"):
        return f"I found {row_count} matching record(s). Most recent job: {first_job_number}."

    first_key = next(iter(first.keys()), None)
    first_value = _format_value(first.get(first_key)) if first_key else "Not available"
    return f"I found {row_count} matching record(s). First result: {first_value}."


def build_rows_adaptive_card(result: dict, max_rows: int = 5) -> Attachment | None:
    if result.get("status") != "success":
        return None

    rows = result.get("rows") or []
    if not rows:
        return None

    shown = min(len(rows), max_rows)
    header = {
        "type": "TextBlock",
        "size": "Medium",
        "weight": "Bolder",
        "text": f"Top Results ({shown} of {len(rows)})",
        "wrap": True,
    }

    subtitle = {
        "type": "TextBlock",
        "text": "Here are the key facts in plain language:",
        "wrap": True,
        "spacing": "Small",
        "isSubtle": True,
    }

    body_blocks: list[dict] = [header, subtitle]
    for idx, row in enumerate(rows[:max_rows], 1):
        items = _display_items(row)
        if not items:
            continue

        pretty_pairs = [f"{label}: {value}" for label, value in items]
        body_blocks.append(
            {
                "type": "TextBlock",
                "text": f"{idx}. " + "; ".join(pretty_pairs),
                "wrap": True,
                "spacing": "Medium",
            }
        )

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body_blocks,
    }
    return CardFactory.adaptive_card(card)


def build_message_activity(result: dict):
    text = build_summary_text(result)
    message = MessageFactory.text(text)

    if card := build_rows_adaptive_card(result):
        message.attachments = [card]

    return message
