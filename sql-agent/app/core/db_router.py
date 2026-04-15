def _normalize_query(user_query: str) -> str:
    return (user_query or "").lower()


def route_database_with_confidence(
    user_query: str, available_dbs: dict, default_db: str
) -> tuple[str, float, list[str]]:
    q = _normalize_query(user_query)
    scores: dict[str, float] = {"PRIME": 0.0, "ENDATA": 0.0, "IN4MO": 0.0}

    explicit_mentions = {name for name in ("prime", "endata", "in4mo") if name in q}

    if "prime" in q:
        scores["PRIME"] = 0.95
    if "endata" in q:
        scores["ENDATA"] = 0.95
    if "in4mo" in q:
        scores["IN4MO"] = 0.95

    prime_hints = {
        "job": 0.85,
        "allocation": 0.85,
        "work order": 0.85,
        "work-order": 0.85,
        "reminder": 0.85,
        "qbcc": 0.9,
        "invoice": 0.8,
        "invoices": 0.8,
        "ar invoice": 0.85,
        "xero": 0.9,
        "hollard": 0.85,
        "brand mapping": 0.8,
        "contract status": 0.8,
        "sow band": 0.8,
        "contract": 0.75,
        "construction": 0.75,
        "pending approval": 0.7,
    }
    for hint, score in prime_hints.items():
        if hint in q:
            scores["PRIME"] = max(scores["PRIME"], score)

    endata_hints = {
        "claim": 0.85,
        "claims": 0.85,
        "insurance": 0.9,
        "policy": 0.8,
        "premium": 0.8,
    }
    for hint, score in endata_hints.items():
        if hint in q:
            scores["ENDATA"] = max(scores["ENDATA"], score)

    in4mo_hints = {
        "inspection": 0.85,
        "repair": 0.85,
        "property": 0.75,
        "damage": 0.7,
    }
    for hint, score in in4mo_hints.items():
        if hint in q:
            scores["IN4MO"] = max(scores["IN4MO"], score)

    available = [db for db in scores if db in available_dbs]
    if not available:
        return default_db, 0.0, []

    primary = max(available, key=lambda db: scores[db])
    confidence = scores[primary]
    ordered_fallbacks = [db for db in sorted(available, key=lambda d: scores[d], reverse=True) if db != primary]

    if confidence == 0.0:
        primary = default_db
        confidence = 0.4
        ordered_fallbacks = [db for db in available if db != primary]

    if explicit_mentions:
        confidence = max(confidence, 0.9)

    return primary, confidence, ordered_fallbacks


def route_database(user_query: str, available_dbs: dict, default_db: str) -> str:
    primary, _, _ = route_database_with_confidence(user_query, available_dbs, default_db)
    return primary