from app.api.messages import normalize_message_request
from app.config import (
    get_allowed_schemas,
    get_available_databases,
    get_default_database_name,
    get_schema_table_limit,
)
from app.core.db_router import route_database
from app.core.db_executor import dataframe_to_records, execute_read_only_query
from app.core.errors import ServiceError
from app.core.join_engine import build_relationship_sql
from app.core.response_formatter import error_response, success_response
from app.core.schema_loader import load_schema_context
from app.core.sql_generator import generate_sql
from app.core.sql_validator import (
    sanitize_sql,
    validate_join_requirements,
    validate_read_only_sql,
    validate_sql,
)


def build_grouped_jobs(rows: list[dict]) -> list[dict] | None:
    if not rows:
        return None

    relation_keys = [
        key
        for key in ("allocationId", "reminderId", "workOrderId")
        if any(key in row for row in rows)
    ]
    if not relation_keys:
        return None

    if not all("id" in row and "jobNumber" in row for row in rows):
        return None

    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        group_key = (str(row["id"]), str(row["jobNumber"]))
        if group_key not in grouped:
            item = {
                "id": row["id"],
                "jobNumber": row["jobNumber"],
            }
            for rel_key in relation_keys:
                field_name = f"{rel_key[:-2]}s"  # allocationId -> allocations
                item[field_name] = []
            grouped[group_key] = item

        for rel_key in relation_keys:
            rel_value = row.get(rel_key)
            field_name = f"{rel_key[:-2]}s"
            if rel_value is not None and rel_value not in grouped[group_key][field_name]:
                grouped[group_key][field_name].append(rel_value)

    return list(grouped.values())


def generate_valid_sql(
    user_query: str,
    schema_text: str,
    fk_text: str,
    database_name: str,
    allowed_tables: set[str],
    allowed_columns_by_table: dict[str, set[str]],
    allowed_schemas: set[str],
) -> str:
    max_attempts = 2
    current_query = user_query
    last_error: Exception | None = None
    base_query_lower = user_query.lower()

    for attempt in range(max_attempts):
        sql = generate_sql(
            user_query=current_query,
            schema_text=schema_text,
            fk_text=fk_text,
            database_name=database_name,
        )

        try:
            validate_join_requirements(user_query, sql)
            validate_sql(sql)
            sql = sanitize_sql(sql)
            validate_read_only_sql(
                sql,
                allowed_tables=allowed_tables,
                allowed_columns_by_table=allowed_columns_by_table,
                allowed_schemas=allowed_schemas,
            )
            return sql
        except Exception as exc:
            last_error = exc
            print(f"VALIDATION FAILED (attempt {attempt + 1}/{max_attempts}): {exc}")

            relationship_fix_hint = ""
            if "job" in base_query_lower and "allocation" in base_query_lower:
                relationship_fix_hint = (
                    "Required relationship: JOIN [t_jobs] j ON ... with [t_allocations] a ON j.id = a.jobId. "
                    "Use both tables in FROM/JOIN and project business-relevant columns."
                )
            elif "job" in base_query_lower and "reminder" in base_query_lower:
                relationship_fix_hint = (
                    "Required relationship: JOIN [t_jobs] j with [t_reminders] r ON j.id = r.jobId."
                )
            elif "job" in base_query_lower and (
                "work order" in base_query_lower
                or "work-order" in base_query_lower
                or "work orders" in base_query_lower
            ):
                relationship_fix_hint = (
                    "Required relationship: JOIN [t_jobs] j with [t_work-orders] w ON j.id = w.jobId."
                )

            current_query = (
                f"Original request: {user_query}\n\n"
                "Previous SQL was invalid because:\n"
                f"{exc}\n\n"
                f"{relationship_fix_hint}\n"
                "Fix the SQL and follow all JOIN rules strictly."
            )

    raise ServiceError(f"Failed to generate valid SQL after retries: {last_error}")


def process_message_request(body: dict) -> tuple[dict, bool]:
    try:
        request = normalize_message_request(body)

        dbs = get_available_databases()
        if not dbs:
            raise ServiceError("No valid database configuration found")

        default_db = get_default_database_name(dbs)
        if not default_db:
            raise ServiceError("DEFAULT_DATABASE could not be resolved")

        if request.get("database_explicit"):
            selected_db = request["database"] if request["database"] in dbs else default_db
        else:
            selected_db = route_database(request["message"], dbs, default_db)
            if selected_db not in dbs:
                selected_db = default_db

        print("DEFAULT DB:", default_db)
        print("SELECTED DB:", selected_db)

        schema_context = load_schema_context(
            database_name=selected_db,
            user_message=request["message"],
            max_tables=get_schema_table_limit(),
        )

        allowed_tables = {table.lower() for table in schema_context["schema"].keys()}
        allowed_columns_by_table = {
            table.lower(): {column.lower() for column in columns}
            for table, columns in schema_context["schema"].items()
        }
        allowed_schemas = get_allowed_schemas()

        sql = build_relationship_sql(
            user_query=request["message"],
            schema=schema_context["schema"],
            foreign_keys=schema_context["foreign_keys"],
        )

        if not sql:
            sql = generate_valid_sql(
                user_query=request["message"],
                schema_text=schema_context["schema_text"],
                fk_text=schema_context["fk_text"],
                database_name=schema_context.get("database", selected_db),
                allowed_tables=allowed_tables,
                allowed_columns_by_table=allowed_columns_by_table,
                allowed_schemas=allowed_schemas,
            )
        else:
            sql = sanitize_sql(sql)
            validate_join_requirements(request["message"], sql)
            validate_read_only_sql(
                sql,
                allowed_tables=allowed_tables,
                allowed_columns_by_table=allowed_columns_by_table,
                allowed_schemas=allowed_schemas,
            )

        db_config = dbs[selected_db]
        df = execute_read_only_query(
            db_config=db_config,
            sql=sql,
            allowed_tables=allowed_tables,
            allowed_columns_by_table=allowed_columns_by_table,
            allowed_schemas=allowed_schemas,
            max_rows=500,
        )
        rows = dataframe_to_records(df)
        grouped_jobs = build_grouped_jobs(rows)

        result = success_response(
            sql=sql,
            rows=rows,
            jobs=grouped_jobs,
            message="SQL generated, validated, and executed successfully",
        )
        return result, request["is_bot"]

    except ServiceError as exc:
        return error_response(str(exc)), bool(body.get("type"))
    except Exception as exc:
        return error_response(str(exc)), bool(body.get("type"))
