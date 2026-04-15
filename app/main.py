import logging
import re
import time

from app.api.messages import normalize_message_request
from app.config import (
    get_allowed_schemas,
    get_available_databases,
    get_default_database_name,
    get_schema_table_limit,
)
from app.core.db_router import route_database_with_confidence
from app.core.db_executor import dataframe_to_records, execute_read_only_query
from app.core.errors import ServiceError
from app.core.intent_classifier import IntentResult, classify_intent
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


def _looks_like_kql_query(text: str) -> bool:
    lowered = (text or "").lower()
    kql_markers = [
        "| where",
        "| project",
        "| order by",
        "| take",
        "ago(",
        "resultcode",
        "operation_id",
        "requests",
        "traces",
        "exceptions",
    ]
    return any(marker in lowered for marker in kql_markers)


def _is_blocked_request(text: str) -> bool:
    lowered = f" {(text or '').lower()} "
    write_tokens = [" insert ", " update ", " delete ", " drop ", " alter ", " truncate ", " merge "]
    prompt_injection_tokens = [" ignore all rules", "ignore previous", "bypass", "override system", "system prompt"]
    oversharing_tokens = [" no limit ", " all records ", " every related table "]
    return (
        any(token in lowered for token in write_tokens)
        or any(token in lowered for token in prompt_injection_tokens)
        or (" no limit " in lowered and " all records " in lowered)
        or any(token in lowered for token in oversharing_tokens)
    )


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





def _is_relationship_like_query(user_query: str) -> bool:
    query = (user_query or "").lower()
    entity_groups = [
        ["job", "jobs"],
        ["allocation", "allocations"],
        ["reminder", "reminders"],
        ["work order", "work orders", "work-order", "work-orders"],
    ]
    mentioned = sum(1 for group in entity_groups if any(token in query for token in group))
    return mentioned >= 2




def build_business_template_sql(
    user_query: str,
    schema: dict[str, list[str]],
    intent_type: str | None = None,
) -> str | None:
    query = (user_query or "").lower()

    def _find_table(include: list[str], exclude: list[str] | None = None) -> str | None:
        exclude = exclude or []
        for key in schema:
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if all(token in normalized for token in include) and not any(token in normalized for token in exclude):
                return key
        return None

    # Deterministic template: direct allocation work orders (with optional assignee filter).
    if "direct allocation" in query and ("work order" in query or "work orders" in query or "work-order" in query):
        wo_table = _find_table(["work", "order"], exclude=["item", "trade"])
        jobs_table = _find_table(["job"], exclude=["status", "history", "field", "reporting"])
        contacts_table = _find_table(["contact"])
        if wo_table:
            wo_cols = {c.lower(): c for c in schema.get(wo_table, [])}
            jobs_cols = {c.lower(): c for c in schema.get(jobs_table, [])} if jobs_table else {}
            contacts_cols = {c.lower(): c for c in schema.get(contacts_table, [])} if contacts_table else {}

            from_clause = f"FROM {_table_ref(wo_table)} wo"
            select_lines = []

            if jobs_table and "jobid" in wo_cols and "id" in jobs_cols:
                from_clause += f"\nJOIN {_table_ref(jobs_table)} j ON j.[{jobs_cols['id']}] = wo.[{wo_cols['jobid']}]"
                if "jobnumber" in jobs_cols:
                    select_lines.append(f"j.[{jobs_cols['jobnumber']}] AS [jobNumber]")

            if contacts_table and "assignedid" in wo_cols and "id" in contacts_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(contacts_table)} c ON c.[{contacts_cols['id']}] = wo.[{wo_cols['assignedid']}]"
                if "name" in contacts_cols:
                    select_lines.append(f"c.[{contacts_cols['name']}] AS [assignedContact]")

            for col in ["label", "workorderstatus", "workordertype", "costtotal", "selltotal", "createdat"]:
                if col in wo_cols:
                    select_lines.append(f"wo.[{wo_cols[col]}]")

            where_parts = []
            if "workordertype" in wo_cols:
                where_parts.append(f"LOWER(wo.[{wo_cols['workordertype']}]) = 'direct allocation'")
            if "workorderstatus" in wo_cols:
                where_parts.append(
                    f"LOWER(wo.[{wo_cols['workorderstatus']}]) NOT IN ('cancelled','draft','completed')"
                )
            if "richardson" in query and contacts_table and "name" in contacts_cols:
                where_parts.append(f"LOWER(c.[{contacts_cols['name']}]) LIKE '%richardson%plumb%'")

            if not select_lines:
                select_lines = ["wo.[id]"]

            order_by = f"wo.[{wo_cols['createdat']}] DESC" if "createdat" in wo_cols else "wo.[id] DESC"
            where_clause = f"\nWHERE {' AND '.join(where_parts)}" if where_parts else ""
            return (
                "SELECT TOP 20\n"
                f"    {', '.join(select_lines)}\n"
                f"{from_clause}"
                f"{where_clause}\n"
                f"ORDER BY {order_by}"
            )

    # Deterministic template: allocation status history with job/allocation labels.
    if "allocation" in query and "status history" in query:
        sh_table = _find_table(["status", "histor"])
        alloc_table = _find_table(["alloc"], exclude=["status"])
        jobs_table = _find_table(["job"], exclude=["status", "history", "field", "reporting"])
        if sh_table and alloc_table:
            sh_cols = {c.lower(): c for c in schema.get(sh_table, [])}
            a_cols = {c.lower(): c for c in schema.get(alloc_table, [])}
            j_cols = {c.lower(): c for c in schema.get(jobs_table, [])} if jobs_table else {}

            select_lines = []
            if jobs_table and "jobid" in sh_cols and "id" in j_cols:
                select_lines.append(f"j.[{j_cols.get('jobnumber', j_cols['id'])}] AS [jobNumber]")
            if "allocationnumber" in a_cols:
                select_lines.append(f"a.[{a_cols['allocationnumber']}] AS [allocationNumber]")
            for col in ["oldstatus", "newstatus", "createdat", "objectid", "objecttype"]:
                if col in sh_cols:
                    select_lines.append(f"sh.[{sh_cols[col]}]")
            if not select_lines:
                select_lines = ["sh.[id]"]

            from_clause = f"FROM {_table_ref(sh_table)} sh"
            if jobs_table and "jobid" in sh_cols and "id" in j_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(jobs_table)} j ON j.[{j_cols['id']}] = sh.[{sh_cols['jobid']}]"
            if "objectid" in sh_cols and "id" in a_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(alloc_table)} a ON a.[{a_cols['id']}] = sh.[{sh_cols['objectid']}]"

            where_parts = []
            if "objecttype" in sh_cols:
                where_parts.append(f"LOWER(sh.[{sh_cols['objecttype']}]) = 'allocation'")
            where_clause = f"\nWHERE {' AND '.join(where_parts)}" if where_parts else ""
            order_by = f"sh.[{sh_cols['createdat']}] DESC" if "createdat" in sh_cols else "sh.[id] DESC"
            return (
                "SELECT TOP 20\n"
                f"    {', '.join(select_lines)}\n"
                f"{from_clause}"
                f"{where_clause}\n"
                f"ORDER BY {order_by}"
            )

    # Deterministic template: allocation + AP totals + work-order detail.
    if "allocation" in query and "ap" in query and "work order" in query:
        alloc_table = _find_table(["alloc"], exclude=["status"])
        jobs_table = _find_table(["job"], exclude=["status", "history", "field", "reporting"])
        wo_table = _find_table(["work", "order"], exclude=["item", "trade"])
        ap_table = _find_table(["account", "payable", "invoice"])
        if alloc_table and wo_table and ap_table:
            a_cols = {c.lower(): c for c in schema.get(alloc_table, [])}
            j_cols = {c.lower(): c for c in schema.get(jobs_table, [])} if jobs_table else {}
            w_cols = {c.lower(): c for c in schema.get(wo_table, [])}
            ap_cols = {c.lower(): c for c in schema.get(ap_table, [])}

            select_lines = []
            if jobs_table and "id" in j_cols and "jobid" in a_cols and "jobnumber" in j_cols:
                select_lines.append(f"j.[{j_cols['jobnumber']}] AS [jobNumber]")
            if "allocationnumber" in a_cols:
                select_lines.append(f"a.[{a_cols['allocationnumber']}] AS [allocationNumber]")
            if "label" in w_cols:
                select_lines.append(f"w.[{w_cols['label']}] AS [workOrderLabel]")
            if "workorderstatus" in w_cols:
                select_lines.append(f"w.[{w_cols['workorderstatus']}] AS [workOrderStatus]")
            select_lines.append("SUM(COALESCE(ap.[subtotal], 0)) AS [apTotalExTax]")

            from_clause = f"FROM {_table_ref(alloc_table)} a"
            if jobs_table and "id" in j_cols and "jobid" in a_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(jobs_table)} j ON j.[{j_cols['id']}] = a.[{a_cols['jobid']}]"
            if "allocationid" in w_cols and "id" in a_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(wo_table)} w ON w.[{w_cols['allocationid']}] = a.[{a_cols['id']}]"
            if "workorderid" in ap_cols and "id" in w_cols:
                from_clause += f"\nLEFT JOIN {_table_ref(ap_table)} ap ON ap.[{ap_cols['workorderid']}] = w.[{w_cols['id']}]"

            group_by = []
            for expr in select_lines:
                if expr.startswith("SUM("):
                    continue
                group_by.append(expr.split(" AS ")[0])

            order_by = "[apTotalExTax] DESC"
            return (
                "SELECT TOP 20\n"
                f"    {', '.join(select_lines)}\n"
                f"{from_clause}\n"
                f"GROUP BY {', '.join(group_by)}\n"
                f"ORDER BY {order_by}"
            )

    # Deterministic template: reminder productivity for current month by user.
    if "reminder" in query and ("average days to complete" in query or "average reminders per day" in query):
        reminders_table = _find_table(["remind"])
        users_table = _find_table(["user"])
        if reminders_table and users_table:
            r_cols = {c.lower(): c for c in schema.get(reminders_table, [])}
            u_cols = {c.lower(): c for c in schema.get(users_table, [])}
            if all(token in r_cols for token in ["userid", "createdat", "updatedat"]) and "id" in u_cols:
                user_name_col = u_cols.get("fullname") or u_cols.get("name") or u_cols["id"]
                status_col = r_cols.get("reminderstatus")
                status_filter = (
                    f"CASE WHEN LOWER(r.[{status_col}]) = 'completed' THEN DATEDIFF(DAY, r.[{r_cols['createdat']}], r.[{r_cols['updatedat']}]) END"
                    if status_col
                    else f"DATEDIFF(DAY, r.[{r_cols['createdat']}], r.[{r_cols['updatedat']}])"
                )
                return (
                    "SELECT TOP 20\n"
                    f"    u.[{user_name_col}] AS [user],\n"
                    f"    CAST(AVG({status_filter}) AS DECIMAL(10,1)) AS [avgDaysToComplete],\n"
                    f"    CAST(CAST(COUNT(1) AS FLOAT) / NULLIF(COUNT(DISTINCT CAST(r.[{r_cols['createdat']}] AS DATE)), 0) AS DECIMAL(10,1)) AS [avgRemindersPerDay]\n"
                    f"FROM {_table_ref(reminders_table)} r\n"
                    f"JOIN {_table_ref(users_table)} u ON u.[{u_cols['id']}] = r.[{r_cols['userid']}]\n"
                    f"WHERE r.[{r_cols['createdat']}] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)\n"
                    f"GROUP BY u.[{user_name_col}]\n"
                    f"ORDER BY u.[{user_name_col}]"
                )

    # Deterministic template: model views for contract/pending band reporting.
    if "contract" in query and "band" in query:
        contract_table = next((t for t in schema if t.lower() in {"model.contract", "contract"}), None)
        if contract_table:
            return f"SELECT TOP 20 * FROM {_table_ref(contract_table)} ORDER BY [jobNumber] DESC"
    if "pending approval" in query and "band" in query:
        pending_table = next((t for t in schema if t.lower() in {"model.pending", "pending"}), None)
        if pending_table:
            return f"SELECT TOP 20 * FROM {_table_ref(pending_table)} ORDER BY [jobNumber] DESC"

    # Everything else goes to the LLM — it handles JOINs, filters, and
    # aggregations better than a generic single-table template ever could.
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


def _compute_null_ratio(rows: list[dict]) -> float:
    if not rows:
        return 1.0
    total = 0
    nulls = 0
    for row in rows:
        for value in row.values():
            total += 1
            if value is None:
                nulls += 1
    if total == 0:
        return 1.0
    return nulls / total


def _detect_suspicious_aggregate(rows: list[dict]) -> bool:
    if not rows:
        return False
    numeric_values = []
    for row in rows:
        for value in row.values():
            if isinstance(value, (int, float)):
                numeric_values.append(value)
    if not numeric_values:
        return False
    non_null = [value for value in numeric_values if value is not None]
    if not non_null:
        return True
    return all(value == 0 for value in non_null)


def _looks_like_non_business_payload(rows: list[dict]) -> bool:
    if not rows:
        return False

    first = rows[0]
    if not isinstance(first, dict):
        return False

    keys = [str(key).lower() for key in first.keys()]
    suspicious_tokens = [
        "suser",
        "user_name",
        "original_login",
        "session",
        "spid",
        "host_name",
        "login",
        "checked_utc",
        "server",
        "information_schema",
    ]
    hits = sum(1 for key in keys if any(token in key for token in suspicious_tokens))
    return hits >= 2


def _aggregation_intent_mismatch(rows: list[dict], intent: IntentResult) -> bool:
    if intent.intent not in {"AGGREGATION", "TREND"}:
        return False
    if not rows:
        return False

    first = rows[0]
    has_numeric = any(isinstance(value, (int, float)) for value in first.values())
    return not has_numeric


def evaluate_result_quality(rows: list[dict], intent: IntentResult) -> dict:
    flags: list[str] = []
    if not rows:
        flags.append("empty_result")

    if _looks_like_non_business_payload(rows):
        flags.append("non_business_payload")

    null_ratio = _compute_null_ratio(rows)
    if null_ratio >= 0.6:
        flags.append("null_heavy")

    if intent.intent in {"AGGREGATION", "TREND"} and _detect_suspicious_aggregate(rows):
        flags.append("suspicious_aggregate")

    if _aggregation_intent_mismatch(rows, intent):
        flags.append("intent_mismatch")

    return {
        "flags": flags,
        "null_ratio": round(null_ratio, 3),
        "row_count": len(rows),
    }


def _compute_confidence(routing_confidence: float, quality: dict, fallback_used: bool) -> float:
    score = routing_confidence
    if "empty_result" in quality.get("flags", []):
        score -= 0.4
    if "null_heavy" in quality.get("flags", []):
        score -= 0.2
    if "suspicious_aggregate" in quality.get("flags", []):
        score -= 0.2
    if fallback_used:
        score -= 0.1
    return max(0.0, min(1.0, round(score, 2)))


def _run_query_for_db(
    request: dict,
    selected_db: str,
    intent: IntentResult,
    dbs: dict,
    timings: dict[str, float] | None = None,
) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    schema_context = load_schema_context(
        database_name=selected_db,
        user_message=request["message"],
        max_tables=get_schema_table_limit(),
    )
    t1 = time.perf_counter()
    if timings is not None:
        timings["schema_load_ms"] = round((t1 - t0) * 1000, 2)

    allowed_tables: set[str] = set()
    allowed_columns_by_table: dict[str, set[str]] = {}
    for table_key, columns in schema_context["schema"].items():
        key_lower = table_key.lower()
        allowed_tables.add(key_lower)

        # Strip type annotations like "(datetime2)" from column names for validation
        column_set = {column.split(" (")[0].lower() for column in columns}
        allowed_columns_by_table.setdefault(key_lower, set()).update(column_set)

        if "." in table_key:
            short_name = table_key.split(".", 1)[1].lower()
            allowed_tables.add(short_name)
            allowed_columns_by_table.setdefault(short_name, set()).update(column_set)

    allowed_schemas = get_allowed_schemas()

    generation_path = ""
    sql = None

    # Always attempt deterministic business templates first for known client query families.
    sql = build_business_template_sql(
        user_query=request["message"],
        schema=schema_context["schema"],
        intent_type=intent.intent,
    )
    if sql:
        generation_path = "business_template"

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
        generation_path = "llm"

    sql = sanitize_sql(sql)
    try:
        validate_join_requirements(request["message"], sql)
    except ServiceError as exc:
        message = str(exc).lower()
        if "join required" in message or "relationship query" in message:
            rel_sql = build_relationship_sql(
                user_query=request["message"],
                schema=schema_context["schema"],
                foreign_keys=schema_context["foreign_keys"],
            )
            if rel_sql:
                sql = sanitize_sql(rel_sql)
                generation_path = "relationship_template"
            else:
                sql = generate_valid_sql(
                    user_query=request["message"],
                    schema_text=schema_context["schema_text"],
                    fk_text=schema_context["fk_text"],
                    database_name=schema_context.get("database", selected_db),
                    allowed_tables=allowed_tables,
                    allowed_columns_by_table=allowed_columns_by_table,
                    allowed_schemas=allowed_schemas,
                )
                generation_path = "llm"
                sql = sanitize_sql(sql)
        else:
            raise

    validate_read_only_sql(
        sql,
        allowed_tables=allowed_tables,
        allowed_columns_by_table=allowed_columns_by_table,
        allowed_schemas=allowed_schemas,
    )

    t2 = time.perf_counter()
    if timings is not None:
        timings["sql_build_ms"] = round((t2 - t1) * 1000, 2)

    db_config = dbs[selected_db]

    # Attempt execution with one retry — if the DB returns a type/syntax error,
    # feed the error back to the LLM so it can self-correct.
    last_exec_error = None
    for exec_attempt in range(2):
        try:
            df = execute_read_only_query(
                db_config=db_config,
                sql=sql,
                allowed_tables=allowed_tables,
                allowed_columns_by_table=allowed_columns_by_table,
                allowed_schemas=allowed_schemas,
                max_rows=500,
                validated=True,
            )
            last_exec_error = None
            break
        except Exception as exec_exc:
            last_exec_error = exec_exc
            if exec_attempt == 0:
                error_msg = str(exec_exc)
                print(f"EXECUTION FAILED (attempt 1), retrying with error context: {error_msg[:300]}")
                retry_query = (
                    f"Original request: {request['message']}\n\n"
                    f"The previous SQL failed at execution with this database error:\n"
                    f"{error_msg[:500]}\n\n"
                    f"Fix the SQL to avoid this error. Common fixes:\n"
                    f"- datetime2 columns: use IS NOT NULL / IS NULL, never = 0 or = 1\n"
                    f"- Use correct column types for comparisons\n"
                    f"- Ensure table/column names match the schema exactly\n"
                )
                sql = generate_valid_sql(
                    user_query=retry_query,
                    schema_text=schema_context["schema_text"],
                    fk_text=schema_context["fk_text"],
                    database_name=schema_context.get("database", selected_db),
                    allowed_tables=allowed_tables,
                    allowed_columns_by_table=allowed_columns_by_table,
                    allowed_schemas=allowed_schemas,
                )
                sql = sanitize_sql(sql)
                validate_read_only_sql(
                    sql,
                    allowed_tables=allowed_tables,
                    allowed_columns_by_table=allowed_columns_by_table,
                    allowed_schemas=allowed_schemas,
                )

    if last_exec_error is not None:
        raise last_exec_error

    t3 = time.perf_counter()
    if timings is not None:
        timings["execute_ms"] = round((t3 - t2) * 1000, 2)
    rows = dataframe_to_records(df)
    grouped_jobs = build_grouped_jobs(rows)

    meta = {
        "intent": intent.intent,
        "intent_reason": intent.reason,
        "generation_path": generation_path,
        "database": selected_db,
    }
    if timings is not None:
        meta["timing_ms"] = timings

    result = success_response(
        sql=sql,
        rows=rows,
        jobs=grouped_jobs,
        message="SQL generated, validated, and executed successfully",
        meta=meta,
    )
    return result, meta


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

    def _classify_error(exc: Exception) -> dict:
        message = str(exc)
        lowered = message.lower()

        hard_markers = [
            "only read queries allowed",
            "blocked sql keyword",
            "blocked sql pattern",
            "only single statement",
        ]
        if any(marker in lowered for marker in hard_markers):
            return {"code": "HARD_SAFETY", "retryable": False, "message": message}

        if "select *" in lowered:
            return {"code": "SELECT_STAR", "retryable": True, "message": message}
        if "top required" in lowered or "must include top" in lowered:
            return {"code": "MISSING_TOP", "retryable": True, "message": message}
        if "column" in lowered and "not allowed" in lowered:
            return {"code": "INVALID_COLUMN", "retryable": True, "message": message}
        if "table" in lowered and "not in the allowed" in lowered:
            return {"code": "INVALID_TABLE", "retryable": True, "message": message}
        if "join required" in lowered or "relationship query" in lowered:
            return {"code": "MISSING_JOIN", "retryable": True, "message": message}

        return {"code": "VALIDATION_FAILED", "retryable": True, "message": message}

    def _build_retry_hint(error_info: dict) -> str:
        allowed_table_list = ", ".join(sorted(allowed_tables))
        allowed_table_hint = f"Allowed tables: {allowed_table_list}"

        col_match = re.search(r"column '([^']+)'", error_info["message"].lower())
        col_key = col_match.group(1) if col_match else ""

        column_hints: list[str] = []
        if error_info["code"] == "INVALID_COLUMN":
            # Show full column list for ALL tables so LLM can self-correct.
            for tbl, cols in sorted(allowed_columns_by_table.items()):
                column_hints.append(f"  {tbl}: {', '.join(sorted(cols))}")
            if col_key:
                column_hints.insert(0, f"Invalid column used: '{col_key}'")
        else:
            # For other errors, show columns only for the specific referenced table.
            table_match = re.search(r"table '([^']+)'", error_info["message"].lower())
            table_key = table_match.group(1) if table_match else ""
            if table_key and table_key in allowed_columns_by_table:
                cols = sorted(allowed_columns_by_table[table_key])
                column_hints.append(f"  {table_key}: {', '.join(cols)}")

        allowed_columns_hint = "Allowed columns by table:\n" + "\n".join(column_hints) if column_hints else ""

        return (
            f"ErrorCode: {error_info['code']}\n"
            f"ErrorMessage: {error_info['message']}\n"
            f"{allowed_table_hint}\n"
            f"{allowed_columns_hint}\n"
            "Fix the SQL directly. Use only allowed tables/columns and follow FK join rules."
        )

    def _build_relationship_hint(query_lower: str) -> str:
        jobs_table = next(
            (t for t in allowed_tables if "job" in t and "status" not in t and "custom" not in t),
            None,
        )
        alloc_table = next((t for t in allowed_tables if "alloc" in t and "status" not in t), None)
        reminder_table = next((t for t in allowed_tables if "remind" in t), None)
        workorder_table = next((t for t in allowed_tables if "work" in t and "order" in t), None)

        if "allocation" in query_lower and jobs_table and alloc_table:
            return (
                f"Required relationship: JOIN [{jobs_table}] j with [{alloc_table}] a ON j.id = a.jobId. "
                "Use both tables in FROM/JOIN and project business-relevant columns."
            )
        if "reminder" in query_lower and jobs_table and reminder_table:
            return f"Required relationship: JOIN [{jobs_table}] j with [{reminder_table}] r ON j.id = r.jobId."
        if ("work order" in query_lower or "work-order" in query_lower) and jobs_table and workorder_table:
            return f"Required relationship: JOIN [{jobs_table}] j with [{workorder_table}] w ON j.id = w.jobId."
        return ""

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

            error_info = _classify_error(exc)
            if not error_info["retryable"]:
                raise ServiceError(error_info["message"]) from exc

            relationship_fix_hint = _build_relationship_hint(base_query_lower)

            current_query = (
                f"Original request: {user_query}\n\n"
                f"{_build_retry_hint(error_info)}\n\n"
                f"{relationship_fix_hint}\n"
                "Fix the SQL and follow all JOIN rules strictly."
            )

    raise ServiceError(f"Failed to generate valid SQL after retries: {last_error}")


def process_message_request(body: dict) -> tuple[dict, bool]:
    try:
        overall_start = time.perf_counter()
        request = normalize_message_request(body)

        if _is_blocked_request(request["message"]):
            return (
                error_response(
                    "Blocked request: this agent supports read-only business analytics queries only.",
                    meta={"intent": "BLOCKED"},
                ),
                request["is_bot"],
            )

        if _looks_like_kql_query(request["message"]):
            return (
                error_response(
                    "This bot answers SQL business data questions only. Run KQL in Azure Monitor Logs.",
                    meta={"intent": "BLOCKED_KQL"},
                ),
                request["is_bot"],
            )

        intent = classify_intent(request["message"])

        dbs = get_available_databases()
        if not dbs:
            raise ServiceError("No valid database configuration found")

        default_db = get_default_database_name(dbs)
        if not default_db:
            raise ServiceError("DEFAULT_DATABASE could not be resolved")

        database_explicit = bool(request.get("database_explicit"))
        if database_explicit:
            selected_db = request["database"] if request["database"] in dbs else default_db
            routing_confidence = 1.0
            fallback_candidates: list[str] = []
        else:
            selected_db, routing_confidence, fallback_candidates = route_database_with_confidence(
                request["message"], dbs, default_db
            )
            if selected_db not in dbs:
                selected_db = default_db

        if intent.intent == "DOMAIN_SPECIFIC":
            routing_confidence = max(routing_confidence, 0.85)
        elif intent.intent == "AGGREGATION":
            routing_confidence = max(routing_confidence, 0.75)

        print("DEFAULT DB:", default_db)
        print("SELECTED DB:", selected_db)

        timings: dict[str, float] = {}
        result, meta = _run_query_for_db(request, selected_db, intent, dbs, timings)

        quality = evaluate_result_quality(result.get("rows", []), intent)
        fallback_used = False

        low_quality_flags = {"null_heavy", "suspicious_aggregate", "non_business_payload"}
        low_quality = any(flag in quality.get("flags", []) for flag in low_quality_flags)
        low_confidence = routing_confidence < 0.6

        if (
            (quality["row_count"] == 0 or (low_confidence and low_quality))
            and not database_explicit
            and routing_confidence < 0.8
        ):
            fallback_db = fallback_candidates[0] if fallback_candidates else None
            if fallback_db and fallback_db != selected_db and fallback_db in dbs:
                fallback_result, fallback_meta = _run_query_for_db(request, fallback_db, intent, dbs, timings)
                fallback_quality = evaluate_result_quality(fallback_result.get("rows", []), intent)
                if fallback_quality["row_count"] > 0:
                    result = fallback_result
                    meta = fallback_meta
                    quality = fallback_quality
                    fallback_used = True

        confidence_score = _compute_confidence(routing_confidence, quality, fallback_used)
        meta.update(
            {
                "routing_confidence": routing_confidence,
                "quality": quality,
                "fallback_used": fallback_used,
                "confidence_score": confidence_score,
            }
        )
        meta["timing_ms"]["total_ms"] = round((time.perf_counter() - overall_start) * 1000, 2)

        # Preserve the SQL in meta so diagnostics can show it even on error/empty results.
        last_sql = result.get("sql", "")
        meta["sql"] = last_sql

        if "non_business_payload" in quality.get("flags", []):
            return (
                error_response(
                    "I could not find business-relevant data for that request. Please refine your request.",
                    sql=last_sql,
                    meta=meta,
                ),
                request["is_bot"],
            )

        if quality.get("row_count", 0) == 0:
            return (
                error_response(
                    "No matching records were found for that request. Try broadening filters or checking the customer/status terms.",
                    sql=last_sql,
                    meta=meta,
                ),
                request["is_bot"],
            )

        logging.info(
            "SQL request meta intent=%s db=%s path=%s confidence=%.2f rows=%s fallback=%s timing_ms=%s",
            meta.get("intent"),
            meta.get("database"),
            meta.get("generation_path"),
            meta.get("confidence_score"),
            meta.get("quality", {}).get("row_count"),
            meta.get("fallback_used"),
            meta.get("timing_ms"),
        )
        result["meta"] = meta
        return result, request["is_bot"]

    except ServiceError as exc:
        return error_response(str(exc), meta={"intent": "UNKNOWN"}), bool(body.get("type"))
    except Exception as exc:
        return error_response(str(exc), meta={"intent": "UNKNOWN"}), bool(body.get("type"))
