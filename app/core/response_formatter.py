def success_response(
    sql: str,
    rows: list[dict],
    message: str = "Query executed successfully",
    jobs: list[dict] | None = None,
) -> dict:
    payload = {
        "status": "success",
        "sql": sql,
        "rows": rows,
        "message": message,
    }
    if jobs is not None:
        payload["jobs"] = jobs
    return payload


def error_response(message: str, sql: str = "") -> dict:
    return {
        "status": "error",
        "sql": sql,
        "rows": [],
        "message": message,
        "error": message,
    }
