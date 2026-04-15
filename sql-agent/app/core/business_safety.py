import re


BLOCKED_SOURCE_TOKENS = {
    "information_schema",
    "sys",
    "session",
    "identity",
    "internal",
    "metadata",
}


DB_ENTITY_HINTS = {
    "PRIME": [
        "job",
        "allocation",
        "reminder",
        "work",
        "qbcc",
        "invoice",
        "xero",
        "report",
        "status",
    ],
    "ENDATA": [
        "claim",
        "insurance",
        "policy",
        "premium",
        "invoice",
        "customer",
        "incident",
    ],
    "IN4MO": [
        "inspection",
        "property",
        "case",
        "report",
        "repair",
        "claim",
    ],
}


def _identifier_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", (value or "").lower()))


def is_system_or_internal_identifier(identifier: str) -> bool:
    lowered = (identifier or "").lower()
    if not lowered:
        return False

    if lowered.startswith("sys.") or lowered == "sys" or lowered.startswith("information_schema"):
        return True

    tokens = _identifier_tokens(lowered)
    return any(token in tokens for token in BLOCKED_SOURCE_TOKENS)


def is_business_table_for_db(database_name: str | None, table_key: str) -> bool:
    if is_system_or_internal_identifier(table_key):
        return False

    db_key = (database_name or "").upper()
    hints = DB_ENTITY_HINTS.get(db_key)
    if not hints:
        return True

    lowered = table_key.lower()
    return any(hint in lowered for hint in hints)


def filter_business_table_candidates(database_name: str | None, table_keys: list[str]) -> list[str]:
    safe = [table for table in table_keys if not is_system_or_internal_identifier(table)]
    db_key = (database_name or "").upper()
    if db_key not in DB_ENTITY_HINTS:
        return safe

    strict = [table for table in safe if is_business_table_for_db(db_key, table)]
    return strict if strict else safe
