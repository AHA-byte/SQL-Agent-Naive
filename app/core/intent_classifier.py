from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentResult:
    intent: str
    reason: str


def classify_intent(user_query: str) -> IntentResult:
    query = (user_query or "").lower().strip()
    if not query:
        return IntentResult(intent="OTHER", reason="empty_query")

    if any(token in query for token in ["group by", "grouped by", "per day", "per month", "trend", "summary"]):
        return IntentResult(intent="AGGREGATION", reason="aggregation_terms")

    if any(token in query for token in ["count", "how many", "total", "average", "avg", "per "]):
        return IntentResult(intent="AGGREGATION", reason="aggregation_metric_terms")

    if any(token in query for token in ["compare", "difference", "delta", "versus", "vs "]):
        return IntentResult(intent="AGGREGATION", reason="comparison_terms")

    if any(token in query for token in ["with allocations", "with reminders", "with work orders", "without allocations", "no allocations", "without reminders", "no reminders"]):
        return IntentResult(intent="RELATIONSHIP", reason="relationship_phrase")

    if any(token in query for token in ["qbcc", "hollard", "invoice productivity", "excess invoiced", "policy number"]):
        return IntentResult(intent="DOMAIN_SPECIFIC", reason="domain_keywords")

    if any(token in query for token in ["recent", "latest", "show", "list", "find"]):
        return IntentResult(intent="SIMPLE_LIST", reason="list_terms")

    return IntentResult(intent="OTHER", reason="fallback")
