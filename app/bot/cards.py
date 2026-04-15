from __future__ import annotations

from botbuilder.core import MessageFactory

from app.core.presentation import build_response_view


def build_message_activity(result: dict):
    view = build_response_view(result, max_items=10)

    parts = [view.get("summary") or "I could not complete that request right now."]
    rows = view.get("rows") or []
    if rows:
        parts.append("\n\n".join(rows))

    insight = view.get("insight")
    if insight:
        parts.append(f"Insight: {insight}")

    # Diagnostics — always shown so issues can be debugged without a separate API call.
    sql = (result.get("sql") or result.get("meta", {}).get("sql") or "").strip()
    meta = result.get("meta") or {}
    diag_lines: list[str] = ["---", "**Diagnostics**"]
    diag_lines.append(f"DB: `{meta.get('database', '?')}` | Path: `{meta.get('generation_path', '?')}` | Intent: `{meta.get('intent', '?')}`")
    timing = meta.get("timing_ms") or {}
    if timing:
        total = timing.get("total_ms", "?")
        sql_ms = timing.get("sql_build_ms", "?")
        exec_ms = timing.get("execute_ms", "?")
        diag_lines.append(f"Timing: total={total}ms | sql_build={sql_ms}ms | exec={exec_ms}ms")
    quality = meta.get("quality") or {}
    flags = quality.get("flags") or []
    diag_lines.append(f"Rows: {quality.get('row_count', '?')} | Null ratio: {quality.get('null_ratio', '?')} | Flags: {', '.join(flags) if flags else 'none'}")
    if sql:
        diag_lines.append(f"```sql\n{sql}\n```")
    parts.append("\n\n".join(diag_lines))

    message_text = "\n\n".join(part for part in parts if part).strip()
    activity = MessageFactory.text(message_text)
    activity.text_format = "markdown"
    return activity
