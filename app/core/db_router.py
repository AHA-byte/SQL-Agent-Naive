def route_database(user_query: str, available_dbs: dict, default_db: str) -> str:
    q = user_query.lower()

    if "prime" in q:
        return "PRIME" if "PRIME" in available_dbs else default_db
    if "endata" in q:
        return "ENDATA" if "ENDATA" in available_dbs else default_db
    if "in4mo" in q:
        return "IN4MO" if "IN4MO" in available_dbs else default_db

    prime_hints = [
        "job",
        "allocation",
        "work order",
        "work-order",
        "reminder",
        "qbcc",
        "invoice",
        "invoices",
        "ar invoice",
        "xero",
        "hollard",
        "brand mapping",
        "contract status",
        "sow band",
        "hollard",
        "xero",
        "contract",
        "construction",
        "pending approval",
    ]
    if any(hint in q for hint in prime_hints):
        return "PRIME" if "PRIME" in available_dbs else default_db

    if "claim" in q or "insurance" in q:
        return "ENDATA" if "ENDATA" in available_dbs else default_db

    if "inspection" in q or "repair" in q:
        return "IN4MO" if "IN4MO" in available_dbs else default_db

    return default_db