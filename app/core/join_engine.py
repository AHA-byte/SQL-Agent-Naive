from app.core.errors import ServiceError


ENTITY_TABLE_MAP = {
    "jobs": "jobs",
    "job": "jobs",
    "allocations": "allocations",
    "allocation": "allocations",
    "reminders": "reminders",
    "reminder": "reminders",
    "work orders": "work_orders",
    "work order": "work_orders",
    "work-orders": "work_orders",
    "work-order": "work_orders",
}


STATIC_FK_RELATIONS = {
    ("t_work-orders", "t_jobs"): ("jobId", "id"),
    ("t_work-orders", "t_allocations"): ("allocationId", "id"),
    ("t_allocations", "t_jobs"): ("jobId", "id"),
    ("t_reminders", "t_jobs"): ("jobId", "id"),
    ("work-orders", "jobs"): ("jobId", "id"),
    ("work-orders", "allocations"): ("allocationId", "id"),
    ("allocations", "jobs"): ("jobId", "id"),
    ("reminders", "jobs"): ("jobId", "id"),
}


def _table_ref(table_key: str) -> str:
    if "." in table_key:
        schema_name, table_name = table_key.split(".", 1)
        return f"[{schema_name}].[{table_name}]"
    return f"[{table_key}]"


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _column_names(columns: list[str]) -> set[str]:
    return {str(col).split(" (")[0].lower() for col in columns}


def _table_scores_for_concept(table_key: str, columns: list[str], concept: str) -> int:
    normalized_table = _norm(table_key)
    cols = _column_names(columns)

    score = 0
    if concept == "jobs":
        if "id" in cols:
            score += 8
        if "jobnumber" in cols:
            score += 6
        if "job" in normalized_table:
            score += 4
        if normalized_table.startswith("tjobs"):
            score += 6
        if normalized_table.startswith("reporting"):
            score -= 4
    elif concept == "allocations":
        if "jobid" in cols:
            score += 8
        if "id" in cols:
            score += 4
        if "alloc" in normalized_table:
            score += 5
        if normalized_table.startswith("tallocations"):
            score += 4
    elif concept == "reminders":
        if "jobid" in cols:
            score += 8
        if "id" in cols:
            score += 4
        if "remind" in normalized_table:
            score += 5
        if normalized_table.startswith("treminders"):
            score += 4
    elif concept == "work_orders":
        if "jobid" in cols:
            score += 8
        if "id" in cols:
            score += 4
        if "workorder" in normalized_table:
            score += 6
        if normalized_table.startswith("tworkorders"):
            score += 4

    return score


def _resolve_concept_tables(schema: dict[str, list[str]]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    concepts = ["jobs", "allocations", "reminders", "work_orders"]
    for concept in concepts:
        ranked = sorted(
            schema.items(),
            key=lambda item: (_table_scores_for_concept(item[0], item[1], concept), item[0]),
            reverse=True,
        )
        if not ranked:
            continue
        best_table, _ = ranked[0]
        if _table_scores_for_concept(best_table, schema[best_table], concept) > 0:
            resolved[concept] = best_table
    return resolved


def _build_on_clause(
    left_table: str,
    right_table: str,
    left_alias: str,
    right_alias: str,
    fk_relations: dict[tuple[str, str], tuple[str, str]],
) -> str | None:
    left_key = left_table.lower()
    right_key = right_table.lower()

    if (left_key, right_key) in fk_relations:
        left_col, right_col = fk_relations[(left_key, right_key)]
        return f"{left_alias}.[{left_col}] = {right_alias}.[{right_col}]"

    if (right_key, left_key) in fk_relations:
        right_col, left_col = fk_relations[(right_key, left_key)]
        return f"{right_alias}.[{right_col}] = {left_alias}.[{left_col}]"

    return None


def _build_on_clause_from_columns(
    left_table: str,
    right_table: str,
    left_alias: str,
    right_alias: str,
    schema: dict[str, list[str]],
) -> str | None:
    left_cols = {col.split(" (")[0].lower() for col in schema.get(left_table, [])}
    right_cols = {col.split(" (")[0].lower() for col in schema.get(right_table, [])}

    # Prefer direct work-order <-> allocation relationship when available.
    if "id" in left_cols and "allocationid" in right_cols:
        return f"{right_alias}.[allocationId] = {left_alias}.[id]"
    if "allocationid" in left_cols and "id" in right_cols:
        return f"{left_alias}.[allocationId] = {right_alias}.[id]"

    if "id" in left_cols and "jobid" in right_cols:
        return f"{right_alias}.[jobId] = {left_alias}.[id]"
    if "jobid" in left_cols and "id" in right_cols:
        return f"{left_alias}.[jobId] = {right_alias}.[id]"

    if "jobnumber" in left_cols and "jobnumber" in right_cols:
        return f"{left_alias}.[jobNumber] = {right_alias}.[jobNumber]"

    return None


def _alias_for_table(table_key: str, default_alias: str) -> str:
    normalized = _norm(table_key)
    if "job" in normalized:
        return "j"
    if "alloc" in normalized:
        return "a"
    if "remind" in normalized:
        return "r"
    if "workorder" in normalized:
        return "w"
    return default_alias


def build_fk_relations(foreign_keys: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    relations: dict[tuple[str, str], tuple[str, str]] = {
        (left.lower(), right.lower()): cols for (left, right), cols in STATIC_FK_RELATIONS.items()
    }
    for fk in foreign_keys:
        parent_table = fk["parent_table"]
        parent_column = fk["parent_column"]
        referenced_table = fk["referenced_table"]
        referenced_column = fk["referenced_column"]

        parent_schema = fk.get("parent_schema") or "dbo"
        referenced_schema = fk.get("referenced_schema") or "dbo"

        parent_variants = {
            parent_table,
            f"{parent_schema}.{parent_table}",
        }
        referenced_variants = {
            referenced_table,
            f"{referenced_schema}.{referenced_table}",
        }

        for left in parent_variants:
            for right in referenced_variants:
                relations[(left.lower(), right.lower())] = (parent_column, referenced_column)

    return relations


def detect_intent_entities(user_query: str, schema: dict[str, list[str]]) -> list[str]:
    q = (user_query or "").lower()
    concepts: list[str] = []
    resolved_tables = _resolve_concept_tables(schema)
    allocation_is_modifier = any(
        phrase in q
        for phrase in [
            "allocation work order",
            "allocation work orders",
            "direct allocation work order",
            "direct allocation work orders",
        ]
    )

    for phrase, concept in ENTITY_TABLE_MAP.items():
        if phrase in q and concept in resolved_tables and concept not in concepts:
            if concept == "allocations" and allocation_is_modifier:
                continue
            concepts.append(concept)

    if "jobs" in concepts and len(concepts) > 1:
        concepts = ["jobs"] + [concept for concept in concepts if concept != "jobs"]

    entities = [resolved_tables[concept] for concept in concepts if concept in resolved_tables]
    return entities


def is_relationship_query(user_query: str, entities: list[str]) -> bool:
    q = (user_query or "").lower()
    relationship_hint = any(token in q for token in [" with ", " relationship", "relationships", " join ", " joined "])
    return len(entities) >= 2 or relationship_hint


def _build_join(
    left_table: str,
    right_table: str,
    left_alias: str,
    right_alias: str,
    fk_relations: dict[tuple[str, str], tuple[str, str]],
) -> str:
    on_clause = _build_on_clause(left_table, right_table, left_alias, right_alias, fk_relations)
    if on_clause:
        return (
            f"FROM {_table_ref(left_table)} {left_alias}\n"
            f"JOIN {_table_ref(right_table)} {right_alias} ON {on_clause}"
        )

    raise ServiceError(f"No FK relationship found between {left_table} and {right_table}")


def build_relationship_sql(user_query: str, schema: dict[str, list[str]], foreign_keys: list[dict]) -> str | None:
    available_tables = set(schema.keys())
    entities = detect_intent_entities(user_query, schema)
    query_text = (user_query or "").lower()
    concept_tables = _resolve_concept_tables(schema)
    fk_relations = build_fk_relations(foreign_keys)

    if not is_relationship_query(user_query, entities):
        return None

    if len(entities) < 2:
        return None

    # For multi-entity requests, use deterministic templates only for known patterns.
    if len(entities) > 2:
        jobs_table = concept_tables.get("jobs")
        reminders_table = concept_tables.get("reminders")
        allocations_table = concept_tables.get("allocations")
        work_orders_table = concept_tables.get("work_orders")

        if jobs_table and reminders_table and allocations_table and (
            "with allocations" in query_text
            and "reminder" in query_text
            and "without" not in query_text
            and "no " not in query_text
        ):
            on_j_r = _build_on_clause(jobs_table, reminders_table, "j", "r", fk_relations)
            on_j_a = _build_on_clause(jobs_table, allocations_table, "j", "a", fk_relations)
            if not on_j_r:
                on_j_r = _build_on_clause_from_columns(jobs_table, reminders_table, "j", "r", schema)
            if not on_j_a:
                on_j_a = _build_on_clause_from_columns(jobs_table, allocations_table, "j", "a", schema)
            if not on_j_r or not on_j_a:
                return None

            order_by_col = "j.[createdAt]" if "createdAt" in schema[jobs_table] else "j.[id]"
            return (
                "SELECT TOP 20\n"
                "    j.[id],\n"
                + ("    j.[jobNumber],\n" if "jobNumber" in schema[jobs_table] else "")
                + "    a.[id] AS [allocationId],\n"
                + "    r.[id] AS [reminderId]\n"
                + f"FROM {_table_ref(jobs_table)} j\n"
                + f"JOIN {_table_ref(allocations_table)} a ON {on_j_a}\n"
                + f"JOIN {_table_ref(reminders_table)} r ON {on_j_r}\n"
                + f"ORDER BY {order_by_col} DESC"
            )

        if jobs_table and reminders_table and allocations_table and (
            "without allocation" in query_text
            or "no allocation" in query_text
            or "without allocations" in query_text
        ):
            if not {jobs_table, reminders_table, allocations_table}.issubset(available_tables):
                return None

            on_j_r = _build_on_clause(jobs_table, reminders_table, "j", "r", fk_relations)
            on_j_a = _build_on_clause(jobs_table, allocations_table, "j", "a", fk_relations)
            if not on_j_r:
                on_j_r = _build_on_clause_from_columns(jobs_table, reminders_table, "j", "r", schema)
            if not on_j_a:
                on_j_a = _build_on_clause_from_columns(jobs_table, allocations_table, "j", "a", schema)
            if not on_j_r or not on_j_a:
                return None

            order_by_col = "j.[createdAt]" if "createdAt" in schema[jobs_table] else "j.[id]"
            return (
                "SELECT TOP 20\n"
                "    j.[id],\n"
                + ("    j.[jobNumber],\n" if "jobNumber" in schema[jobs_table] else "")
                + "    r.[id] AS [reminderId]\n"
                + f"FROM {_table_ref(jobs_table)} j\n"
                + f"JOIN {_table_ref(reminders_table)} r ON {on_j_r}\n"
                + f"LEFT JOIN {_table_ref(allocations_table)} a ON {on_j_a}\n"
                + "WHERE a.[id] IS NULL\n"
                + f"ORDER BY {order_by_col} DESC"
            )

        if jobs_table and reminders_table and work_orders_table and (
            "no completed work order" in query_text
            or "no completed work orders" in query_text
            or "without completed work order" in query_text
            or "without completed work orders" in query_text
        ):
            if not {jobs_table, reminders_table, work_orders_table}.issubset(available_tables):
                return None

            on_j_r = _build_on_clause(jobs_table, reminders_table, "j", "r", fk_relations)
            on_j_w = _build_on_clause(jobs_table, work_orders_table, "j", "w", fk_relations)
            if not on_j_r:
                on_j_r = _build_on_clause_from_columns(jobs_table, reminders_table, "j", "r", schema)
            if not on_j_w:
                on_j_w = _build_on_clause_from_columns(jobs_table, work_orders_table, "j", "w", schema)
            if not on_j_r or not on_j_w:
                return None

            order_by_col = "j.[createdAt]" if "createdAt" in schema[jobs_table] else "j.[id]"
            status_predicate = "LOWER(w.[workOrderStatus]) = 'completed'"
            if "workOrderStatus" not in schema[work_orders_table]:
                status_predicate = "1 = 1"

            return (
                "SELECT TOP 20\n"
                "    j.[id],\n"
                + ("    j.[jobNumber],\n" if "jobNumber" in schema[jobs_table] else "")
                + "    r.[id] AS [reminderId]\n"
                + f"FROM {_table_ref(jobs_table)} j\n"
                + f"JOIN {_table_ref(reminders_table)} r ON {on_j_r}\n"
                + f"LEFT JOIN {_table_ref(work_orders_table)} w ON {on_j_w} AND {status_predicate}\n"
                + "WHERE w.[id] IS NULL\n"
                + f"ORDER BY {order_by_col} DESC"
            )

        return None

    # Negative relationship intents are better handled by templates or LLM fallback than fixed inner joins.
    if any(token in query_text for token in [" without ", " no ", " missing ", " not "]):
        jobs_table = concept_tables.get("jobs")
        allocations_table = concept_tables.get("allocations")
        if jobs_table and allocations_table and set(entities) == {jobs_table, allocations_table} and (
            "without allocation" in query_text
            or "without allocations" in query_text
            or "no allocations" in query_text
        ):
            on_j_a = _build_on_clause(jobs_table, allocations_table, "j", "a", fk_relations)
            if not on_j_a:
                on_j_a = _build_on_clause_from_columns(jobs_table, allocations_table, "j", "a", schema)
            if not on_j_a:
                return None

            order_by_col = "j.[createdAt]" if "createdAt" in schema[jobs_table] else "j.[id]"
            return (
                "SELECT TOP 20\n"
                "    j.[id],\n"
                + ("    j.[jobNumber]\n" if "jobNumber" in schema[jobs_table] else "    j.[id] AS [jobId]\n")
                + f"FROM {_table_ref(jobs_table)} j\n"
                + f"LEFT JOIN {_table_ref(allocations_table)} a ON {on_j_a}\n"
                + "WHERE a.[id] IS NULL\n"
                + f"ORDER BY {order_by_col} DESC"
            )
        return None

    if missing_tables := [table for table in entities[:2] if table not in available_tables]:
        return None

    left_table, right_table = entities[0], entities[1]
    left_alias = _alias_for_table(left_table, "a")
    right_alias = _alias_for_table(right_table, "b")

    try:
        join_clause = _build_join(left_table, right_table, left_alias, right_alias, fk_relations)
    except ServiceError:
        on_clause = _build_on_clause_from_columns(left_table, right_table, left_alias, right_alias, schema)
        if not on_clause:
            return None
        join_clause = (
            f"FROM {_table_ref(left_table)} {left_alias}\n"
            f"JOIN {_table_ref(right_table)} {right_alias} ON {on_clause}"
        )

    select_columns = [f"{left_alias}.[id]"]
    if "jobNumber" in schema[left_table]:
        select_columns.append(f"{left_alias}.[jobNumber]")
    if "createdAt" in schema[left_table]:
        select_columns.append(f"{left_alias}.[createdAt]")

    normalized_right = _norm(right_table)
    if "alloc" in normalized_right:
        select_columns.append(f"{right_alias}.[id] AS [allocationId]")
    elif "remind" in normalized_right:
        select_columns.append(f"{right_alias}.[id] AS [reminderId]")
    elif "workorder" in normalized_right:
        if "id" in schema[right_table]:
            select_columns.append(f"{right_alias}.[id] AS [workOrderId]")
        if "label" in schema[right_table]:
            select_columns.append(f"{right_alias}.[label]")
        if "workOrderStatus" in schema[right_table]:
            select_columns.append(f"{right_alias}.[workOrderStatus]")
        if "sellTotal" in schema[right_table]:
            select_columns.append(f"{right_alias}.[sellTotal]")

    select_list = ",\n    ".join(select_columns)
    order_by_col = f"{left_alias}.[createdAt]" if "createdAt" in schema[left_table] else f"{left_alias}.[id]"

    return (
        "SELECT TOP 20\n"
        f"    {select_list}\n"
        f"{join_clause}\n"
        f"ORDER BY {order_by_col} DESC"
    )