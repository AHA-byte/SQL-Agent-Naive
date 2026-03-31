from app.config import get_default_database_name, get_available_databases
from app.core.errors import ServiceError


def _default_database() -> str | None:
    dbs = get_available_databases()
    if not dbs:
        return None
    return get_default_database_name(dbs)


def _extract_user_query(body: dict) -> str:
    # Support multiple client payload formats.
    for key in ("message", "text", "query"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_database_override(query: str, available: set[str]) -> tuple[str, str | None]:
    lowered = query.lower().strip()
    patterns = [
        "db:",
        "database:",
        "use database ",
        "use db ",
        "use ",
    ]

    for prefix in patterns:
        if lowered.startswith(prefix):
            rest = lowered[len(prefix):].strip()
            if not rest:
                return query, None
            token = rest.split()[0].upper().strip(",;:")
            if token in available:
                original_rest = query[len(prefix):].strip()
                # Remove the database token from the front and keep remaining prompt text.
                remaining = original_rest.split(maxsplit=1)
                cleaned_query = remaining[1].strip() if len(remaining) > 1 else ""
                return cleaned_query, token

    return query, None


def normalize_message_request(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ServiceError("Invalid JSON body")

    user_query = _extract_user_query(body)
    if not user_query:
        raise ServiceError("No valid query field provided")

    available_dbs = set(get_available_databases().keys())
    user_query, query_database_override = _extract_database_override(user_query, available_dbs)
    if not user_query:
        raise ServiceError("Query text is required after database selector")

    is_bot = "type" in body

    if is_bot:
        conversation = body.get("conversation") or {}
        user = body.get("from") or {}
        channel_data = body.get("channelData") or {}
        value = body.get("value") or {}
        explicit_database = channel_data.get("database") or value.get("database") or query_database_override

        database = (
            explicit_database
            or _default_database()
        )

        normalized = {
            "message": user_query,
            "conversation_id": conversation.get("id", ""),
            "user_id": user.get("id", ""),
            "database": database,
            "context": {
                "channel_id": body.get("channelId", ""),
                "tenant": channel_data.get("tenant") or {},
                "raw_type": body.get("type", ""),
            },
            "is_bot": True,
            "database_explicit": bool(explicit_database),
        }
    else:
        explicit_database = body.get("database") or query_database_override
        normalized = {
            "message": user_query,
            "conversation_id": body.get("conversation_id", ""),
            "user_id": body.get("user_id", ""),
            "database": explicit_database or _default_database(),
            "context": body.get("context") or {},
            "is_bot": False,
            "database_explicit": bool(explicit_database),
        }

    if not normalized["database"]:
        raise ServiceError("database is required")

    return normalized
