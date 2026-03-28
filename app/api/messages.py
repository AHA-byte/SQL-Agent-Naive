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


def normalize_message_request(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ServiceError("Invalid JSON body")

    user_query = _extract_user_query(body)
    if not user_query:
        raise ServiceError("No valid query field provided")

    is_bot = "type" in body

    if is_bot:
        conversation = body.get("conversation") or {}
        user = body.get("from") or {}
        channel_data = body.get("channelData") or {}
        value = body.get("value") or {}
        explicit_database = channel_data.get("database") or value.get("database")

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
        explicit_database = body.get("database")
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
