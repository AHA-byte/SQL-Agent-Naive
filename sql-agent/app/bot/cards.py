from __future__ import annotations

from botbuilder.core import MessageFactory

from app.core.presentation import build_response_view


def build_message_activity(result: dict):
    view = build_response_view(result, max_items=5)

    parts = [view.get("summary") or "I could not complete that request right now."]
    rows = view.get("rows") or []
    if rows:
        parts.append("\n\n".join(rows))

    insight = view.get("insight")
    if insight:
        parts.append(f"Insight: {insight}")

    message_text = "\n\n".join(part for part in parts if part).strip()
    return MessageFactory.text(message_text)
