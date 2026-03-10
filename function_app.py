import json
import logging

import azure.functions as func

from app.config import get_available_databases
from app.services import (
    ServiceError,
    dataframe_to_records,
    execute_query,
    fetch_schema,
    fetch_table_data,
    format_schema_for_prompt,
    generate_sql,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _json_response(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload, default=str),
        status_code=status,
        mimetype="application/json",
    )


def _parse_body(req: func.HttpRequest) -> dict:
    try:
        return req.get_json()
    except ValueError:
        return {}


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json_response({"status": "ok"})


@app.route(route="databases", methods=["GET"])
def databases(req: func.HttpRequest) -> func.HttpResponse:
    db_names = list(get_available_databases().keys())
    return _json_response({"databases": db_names})


@app.route(route="schema", methods=["POST"])
def schema(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    database = body.get("database")

    if not database:
        return _json_response({"error": "database is required"}, status=400)

    try:
        schema_dict = fetch_schema(database)
        return _json_response(
            {
                "schema": schema_dict,
                "schema_text": format_schema_for_prompt(schema_dict),
            }
        )
    except ServiceError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logging.exception("Unexpected error in /schema")
        return _json_response({"error": f"Unexpected error: {exc}"}, status=500)


@app.route(route="generate-sql", methods=["POST"])
def generate_sql_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    user_query = body.get("user_query", "")
    schema_text = body.get("schema_text", "")

    try:
        sql = generate_sql(user_query, schema_text)
        return _json_response({"sql": sql})
    except ServiceError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logging.exception("Unexpected error in /generate-sql")
        return _json_response({"error": f"Unexpected error: {exc}"}, status=500)


@app.route(route="execute", methods=["POST"])
def execute(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    database = body.get("database")
    sql = body.get("sql", "")
    max_rows = int(body.get("max_rows", 1000))

    if not database:
        return _json_response({"error": "database is required"}, status=400)

    try:
        df = execute_query(database, sql, max_rows=max_rows)
        return _json_response(
            {
                "rows": dataframe_to_records(df),
                "columns": list(df.columns),
                "row_count": int(df.shape[0]),
            }
        )
    except ServiceError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logging.exception("Unexpected error in /execute")
        return _json_response({"error": f"Unexpected error: {exc}"}, status=500)


@app.route(route="table-preview", methods=["POST"])
def table_preview(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    database = body.get("database")
    table = body.get("table")
    limit = int(body.get("limit", 20))

    if not database or not table:
        return _json_response({"error": "database and table are required"}, status=400)

    try:
        df = fetch_table_data(database, table, limit=limit)
        return _json_response(
            {
                "rows": dataframe_to_records(df),
                "columns": list(df.columns),
                "row_count": int(df.shape[0]),
            }
        )
    except ServiceError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logging.exception("Unexpected error in /table-preview")
        return _json_response({"error": f"Unexpected error: {exc}"}, status=500)
