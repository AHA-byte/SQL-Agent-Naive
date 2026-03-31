import re
from datetime import datetime

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


def _table_ref(table_key: str) -> str:
    if "." in table_key:
        schema_name, table_name = table_key.split(".", 1)
        return f"[{schema_name}].[{table_name}]"
    return f"[{table_key}]"


def build_reporting_metrics_sql(user_query: str, schema: dict[str, list[str]]) -> str | None:
    query = (user_query or "").lower()
    wants_grouping = "group by" in query or "grouped by" in query
    wants_brand = "brand" in query
    wants_jobs = "job" in query
    wants_metrics = any(token in query for token in ["metric", "reporting", "summary", "count", "kpi"])
    if not (wants_grouping and wants_brand and wants_jobs and wants_metrics):
        return None

    candidate_table_keys = [
        "reporting.Jobs",
        "Jobs",
        "t_jobs",
    ]

    table_key = next((table for table in candidate_table_keys if table in schema), None)
    if not table_key:
        return None

    columns = schema[table_key]
    # If explicit Brand is unavailable, use the closest business-facing brand proxy.
    brand_column = next(
        (
            column
            for column in ["Brand", "Instructing Client", "Client Relationships", "Client Reference"]
            if column in columns
        ),
        None,
    )
    if not brand_column:
        return None

    created_column = next(
        (column for column in ["Created (Date/Time)", "createdAt", "Created"] if column in columns),
        None,
    )

    table_ref = _table_ref(table_key)
    select_lines = [
        f"[{brand_column}] AS [Brand]",
        "COUNT(1) AS [Job Count]",
    ]
    if created_column:
        select_lines.extend(
            [
                f"MIN([{created_column}]) AS [First Job Created]",
                f"MAX([{created_column}]) AS [Latest Job Created]",
            ]
        )

    select_clause = ",\n    ".join(select_lines)
    return (
        "SELECT TOP 20\n"
        f"    {select_clause}\n"
        f"FROM {table_ref}\n"
        f"WHERE [{brand_column}] IS NOT NULL\n"
        f"GROUP BY [{brand_column}]\n"
        "ORDER BY [Job Count] DESC"
    )


def _extract_since_date(user_query: str) -> str | None:
    query = (user_query or "").lower()
    if match := re.search(r"since\s+(\d{4}-\d{2}-\d{2})", query):
        return match.group(1)

    if match := re.search(r"since\s+([a-z]+)\s+(\d{4})", query):
        month_name = match.group(1)
        year = int(match.group(2))
        month_map = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        month = month_map.get(month_name)
        if month:
            return datetime(year, month, 1).strftime("%Y-%m-%d")

    return None


def build_business_template_sql(user_query: str, schema: dict[str, list[str]]) -> str | None:
    query = (user_query or "").lower()

    if any(token in query for token in ["recent jobs", "latest jobs", "show recent jobs"]):
        table_key = "reporting.Jobs" if "reporting.Jobs" in schema else ("t_jobs" if "t_jobs" in schema else None)
        if table_key:
            table_ref = _table_ref(table_key)
            columns = schema[table_key]
            if table_key == "reporting.Jobs":
                select_cols = [
                    col
                    for col in [
                        "Job Number",
                        "Client Reference",
                        "Type",
                        "Current Status",
                        "Created (Date/Time)",
                    ]
                    if col in columns
                ]
                if select_cols:
                    select_clause = ", ".join(f"[{col}]" for col in select_cols)
                    return (
                        f"SELECT TOP 20 {select_clause}\n"
                        f"FROM {table_ref}\n"
                        "ORDER BY [Created (Date/Time)] DESC"
                    )

            select_cols = [col for col in ["jobNumber", "clientReference", "statusId", "createdAt"] if col in columns]
            if select_cols:
                select_clause = ", ".join(f"[{col}]" for col in select_cols)
                order_col = "createdAt" if "createdAt" in columns else select_cols[0]
                return (
                    f"SELECT TOP 20 {select_clause}\n"
                    f"FROM {table_ref}\n"
                    f"ORDER BY [{order_col}] DESC"
                )

    if (
        "invoice" in query
        and "productivity" in query
        and "creator" in query
        and "day" in query
        and "xero.AR-invoices" in schema
    ):
        columns = schema["xero.AR-invoices"]
        date_col = "Date" if "Date" in columns else None
        creator_col = "CreatedBy" if "CreatedBy" in columns else ("Name" if "Name" in columns else None)
        invoice_id_col = "InvoiceID" if "InvoiceID" in columns else ("InvoiceNumber" if "InvoiceNumber" in columns else None)

        if date_col and creator_col and invoice_id_col:
            since_date = _extract_since_date(user_query) or "2025-06-01"
            return (
                "SELECT TOP 20\n"
                f"    [xero].[AR-invoices].[{creator_col}] AS [Creator],\n"
                f"    CAST([xero].[AR-invoices].[{date_col}] AS DATE) AS [Invoice Date],\n"
                f"    COUNT([xero].[AR-invoices].[{invoice_id_col}]) AS [Invoice Count]\n"
                "FROM [xero].[AR-invoices]\n"
                f"WHERE [xero].[AR-invoices].[{date_col}] >= '{since_date}'\n"
                f"GROUP BY [xero].[AR-invoices].[{creator_col}], CAST([xero].[AR-invoices].[{date_col}] AS DATE)\n"
                "ORDER BY [Invoice Date] DESC, [Creator]"
            )

    if (
        "excess" in query
        and "reversed" in query
        and "balance" in query
        and "job" in query
        and "t_jobs" in schema
        and "xero.AR-invoices" in schema
    ):
        job_cols = schema["t_jobs"]
        invoice_cols = schema["xero.AR-invoices"]
        if all(col in job_cols for col in ["jobNumber", "statusId", "excessAmount"]):
            if all(col in invoice_cols for col in ["Reference", "Status", "AmountPaid", "AmountDue"]):
                return (
                    "SELECT TOP 20\n"
                    "    j.[jobNumber] AS [Job Number],\n"
                    "    j.[statusId] AS [Job Status],\n"
                    "    j.[excessAmount] AS [Excess Invoiced],\n"
                    "    COALESCE(SUM(CASE WHEN UPPER(i.[Status]) IN ('VOIDED', 'DELETED', 'REVERSED') THEN COALESCE(i.[AmountPaid], 0) + COALESCE(i.[AmountDue], 0) ELSE 0 END), 0) AS [Reversed Amount],\n"
                    "    j.[excessAmount] - COALESCE(SUM(COALESCE(i.[AmountPaid], 0) + COALESCE(i.[AmountDue], 0)), 0) AS [Balance]\n"
                    "FROM [t_jobs] j\n"
                    "LEFT JOIN [xero].[AR-invoices] i ON i.[Reference] = j.[jobNumber]\n"
                    "GROUP BY j.[jobNumber], j.[statusId], j.[excessAmount]\n"
                    "ORDER BY [Job Number]"
                )

    if "hollard" in query and "job" in query and "current status" in query and "reporting.Jobs" in schema:
        columns = schema["reporting.Jobs"]
        if all(col in columns for col in ["Job Number", "Instructing Client", "Current Status"]):
            invoice_join = ""
            invoice_select = "'Not available' AS [Invoice-To Entity]"
            if "xero.AR-invoices" in schema and all(
                col in schema["xero.AR-invoices"] for col in ["Reference", "Name"]
            ):
                invoice_join = "LEFT JOIN [xero].[AR-invoices] i ON i.[Reference] = rj.[Job Number]"
                invoice_select = "COALESCE(MAX(i.[Name]), 'Not available') AS [Invoice-To Entity]"

            return (
                "SELECT TOP 20\n"
                "    rj.[Job Number],\n"
                "    rj.[Instructing Client] AS [Brand Mapping],\n"
                f"    {invoice_select},\n"
                "    rj.[Current Status]\n"
                "FROM [reporting].[Jobs] rj\n"
                f"{invoice_join}\n"
                "WHERE LOWER(rj.[Instructing Client]) LIKE '%hollard%'\n"
                "GROUP BY rj.[Job Number], rj.[Instructing Client], rj.[Current Status]\n"
                "ORDER BY rj.[Job Number] DESC"
            )

    if "contract status" in query and "sow band" in query and "reporting.Jobs" in schema:
        columns = schema["reporting.Jobs"]
        if all(col in columns for col in ["Job Number", "Current Status", "Authorised Total (Excl. Tax)"]):
            return (
                "SELECT TOP 20\n"
                "    [Job Number],\n"
                "    [Current Status],\n"
                "    [Authorised Total (Excl. Tax)] AS [SOW],\n"
                "    CASE\n"
                "        WHEN [Authorised Total (Excl. Tax)] < 10000 THEN 'Under 10k'\n"
                "        WHEN [Authorised Total (Excl. Tax)] < 25000 THEN '10k to 25k'\n"
                "        WHEN [Authorised Total (Excl. Tax)] < 50000 THEN '25k to 50k'\n"
                "        ELSE '50k+'\n"
                "    END AS [SOW Band]\n"
                "FROM [reporting].[Jobs]\n"
                "WHERE LOWER([Current Status]) LIKE '%contract%'\n"
                "ORDER BY [Authorised Total (Excl. Tax)] DESC"
            )

    if "qbcc" in query and "reminder" in query and "admin.qbcc" in schema:
        columns = schema["admin.qbcc"]
        wanted = [
            "jobnumber",
            "Reminder",
            "ReminderDate",
            "SOW",
            "QBCC Purch",
            "policy number",
            "contract amount",
            "premium amount",
        ]
        selected = [col for col in wanted if col in columns]
        if selected:
            select_clause = ", ".join(f"[{col}]" for col in selected)
            where_clause = "WHERE LOWER([Reminder]) LIKE '%qbcc%'" if "Reminder" in selected else ""
            return (
                f"SELECT TOP 20 {select_clause}\n"
                "FROM [admin].[qbcc]\n"
                f"{where_clause}\n"
                "ORDER BY [ReminderDate] DESC"
            )

    return None


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

        allowed_tables: set[str] = set()
        allowed_columns_by_table: dict[str, set[str]] = {}
        for table_key, columns in schema_context["schema"].items():
            key_lower = table_key.lower()
            allowed_tables.add(key_lower)

            column_set = {column.lower() for column in columns}
            allowed_columns_by_table.setdefault(key_lower, set()).update(column_set)

            if "." in table_key:
                short_name = table_key.split(".", 1)[1].lower()
                allowed_tables.add(short_name)
                allowed_columns_by_table.setdefault(short_name, set()).update(column_set)

        allowed_schemas = get_allowed_schemas()

        sql = build_reporting_metrics_sql(
            user_query=request["message"],
            schema=schema_context["schema"],
        )

        if not sql:
            sql = build_business_template_sql(
                user_query=request["message"],
                schema=schema_context["schema"],
            )

        if not sql:
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
