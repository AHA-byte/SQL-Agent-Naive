def route_database(user_query: str, available_dbs: dict, default_db: str) -> str:
    q = user_query.lower()

    if "claim" in q or "insurance" in q:
        return "ENDATA" if "ENDATA" in available_dbs else default_db

    if "job" in q or "customer" in q:
        return "PRIME" if "PRIME" in available_dbs else default_db

    if "inspection" in q or "repair" in q:
        return "IN4MO" if "IN4MO" in available_dbs else default_db

    return default_db