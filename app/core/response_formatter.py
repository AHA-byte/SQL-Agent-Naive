def success_response(
    sql: str,
    rows: list[dict],
    message: str = "Query executed successfully",
    jobs: list[dict] | None = None,
    meta: dict | None = None,
) -> dict:
    payload = {
        "status": "success",
        "sql": sql,
        "rows": rows,
        "message": message,
    }
    if jobs is not None:
        payload["jobs"] = jobs
    if meta is not None:
        payload["meta"] = meta
    return payload


def _sanitize_error_message(message: str) -> str:
    """Strip raw SQL/pyodbc/driver details while keeping the actionable part."""
    import re
    lowered = message.lower()
    is_driver_error = (
        "pyodbc" in lowered or "odbc driver" in lowered
        or "sqlexecdirectw" in lowered or "sqlalchemy" in lowered
        or "background on this error" in lowered
    )
    if not is_driver_error:
        return message

    # Extract the SQL Server error message between brackets, e.g.:
    # [SQL Server]Operand type clash: datetime2 is incompatible with tinyint
    sql_server_msg = re.search(r"\[SQL Server\](.*?)(?:\(|$)", message)
    if sql_server_msg:
        detail = sql_server_msg.group(1).strip()
        return f"Query failed: {detail}. Please try rephrasing your request."

    # Extract "Invalid column name 'foo'" or similar
    col_err = re.search(r"(Invalid (?:column|object) name '[^']+')", message, re.IGNORECASE)
    if col_err:
        return f"Query failed: {col_err.group(1)}. Please try rephrasing your request."

    return "The query could not be executed. Please try rephrasing your request."


def error_response(message: str, sql: str = "", meta: dict | None = None) -> dict:
    user_message = _sanitize_error_message(message)
    return {
        "status": "error",
        "sql": sql,
        "rows": [],
        "message": user_message,
        "error": user_message,
        "meta": meta or {},
    }
