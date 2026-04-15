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
        "ar invoice": 0.75,
        "ap invoice": 0.75,
        "accounts payable": 0.75,
        "accounts receivable": 0.75,
        "hollard": 0.85,
        "brand mapping": 0.8,
        "contract status": 0.8,
        "sow band": 0.8,
        "sow": 0.8,
        "contract": 0.75,
        "construction": 0.75,
        "pending approval": 0.7,
        "supplier": 0.75,
        "subcontractor": 0.75,
        "estimate": 0.8,
        "status history": 0.8,
        "notification": 0.75,
        "timesheet": 0.8,
        "roster": 0.8,
        "expense": 0.75,
        "win rate": 0.8,
        # Client/insurer/claim queries are almost always about PRIME t_jobs
        "client": 0.8,
        "client group": 0.9,
        "insurer": 0.9,
        "instructing client": 0.9,
        "markup": 0.85,
        "claim": 0.8,
        "active": 0.7,
        "vulnerable": 0.85,
        "customer contact": 0.8,
        "closed": 0.7,
        "won": 0.75,
        "tag": 0.7,
    }
    for hint, score in prime_hints.items():
        if hint in q:
            scores["PRIME"] = max(scores["PRIME"], score)

    endata_hints = {
        "xero": 0.9,
        "credit note": 0.85,
        "insurance": 0.9,
        "policy": 0.8,
        "premium": 0.8,
        "overdue": 0.75,
    }
    for hint, score in endata_hints.items():
        if hint in q:
            scores["ENDATA"] = max(scores["ENDATA"], score)

    in4mo_hints = {
        "inspection": 0.85,
        "repair": 0.85,
        "property": 0.75,
        "damage": 0.7,
        "lodgement": 0.85,
        "cost control": 0.85,
        "work plan": 0.8,
        "project plan": 0.8,
        "chatroom": 0.8,
    }
    # "claim" alone should NOT trigger IN4MO (it's more likely a PRIME job).
    # Only boost IN4MO if "claim" appears with an IN4MO-specific term.
    _in4mo_specific = {"inspection", "cost control", "work plan", "project plan",
                       "lodgement", "coverage", "loss cause", "in4mo", "chatroom"}
    if any(term in q for term in _in4mo_specific):
        in4mo_hints["claim"] = 0.9
        in4mo_hints["claims"] = 0.9
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