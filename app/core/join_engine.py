from app.core.errors import ServiceError


ENTITY_TABLE_MAP = {
    "jobs": "t_jobs",
    "job": "t_jobs",
    "allocations": "t_allocations",
    "allocation": "t_allocations",
    "reminders": "t_reminders",
    "reminder": "t_reminders",
    "work orders": "t_work-orders",
    "work order": "t_work-orders",
    "work-orders": "t_work-orders",
    "work-order": "t_work-orders",
}


STATIC_FK_RELATIONS = {
    ("t_work-orders", "t_jobs"): ("jobId", "id"),
    ("t_allocations", "t_jobs"): ("jobId", "id"),
    ("t_reminders", "t_jobs"): ("jobId", "id"),
}


def build_fk_relations(foreign_keys: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    relations: dict[tuple[str, str], tuple[str, str]] = dict(STATIC_FK_RELATIONS)
    for fk in foreign_keys:
        parent_table = fk["parent_table"]
        parent_column = fk["parent_column"]
        referenced_table = fk["referenced_table"]
        referenced_column = fk["referenced_column"]
        relations[(parent_table, referenced_table)] = (parent_column, referenced_column)
    return relations


def detect_intent_entities(user_query: str) -> list[str]:
    q = (user_query or "").lower()
    entities: list[str] = []

    for phrase, table in ENTITY_TABLE_MAP.items():
        if phrase in q and table not in entities:
            entities.append(table)

    if "t_jobs" in entities and len(entities) > 1:
        entities = ["t_jobs"] + [entity for entity in entities if entity != "t_jobs"]

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
    if (left_table, right_table) in fk_relations:
        left_col, right_col = fk_relations[(left_table, right_table)]
        return (
            f"FROM [{left_table}] {left_alias}\n"
            f"JOIN [{right_table}] {right_alias} ON {left_alias}.[{left_col}] = {right_alias}.[{right_col}]"
        )

    if (right_table, left_table) in fk_relations:
        right_col, left_col = fk_relations[(right_table, left_table)]
        return (
            f"FROM [{left_table}] {left_alias}\n"
            f"JOIN [{right_table}] {right_alias} ON {right_alias}.[{right_col}] = {left_alias}.[{left_col}]"
        )

    raise ServiceError(f"No FK relationship found between {left_table} and {right_table}")


def build_relationship_sql(user_query: str, schema: dict[str, list[str]], foreign_keys: list[dict]) -> str | None:
    available_tables = set(schema.keys())
    entities = detect_intent_entities(user_query)

    if not is_relationship_query(user_query, entities):
        return None

    if len(entities) < 2:
        raise ServiceError("Relationship query detected but not enough entities were identified")

    missing_tables = [table for table in entities[:2] if table not in available_tables]
    if missing_tables:
        missing_csv = ", ".join(missing_tables)
        raise ServiceError(f"Relationship query tables missing from schema context: {missing_csv}")

    left_table, right_table = entities[0], entities[1]
    aliases = {
        "t_jobs": "j",
        "t_allocations": "a",
        "t_reminders": "r",
        "t_work-orders": "w",
    }
    left_alias = aliases.get(left_table, "a")
    right_alias = aliases.get(right_table, "b")

    fk_relations = build_fk_relations(foreign_keys)
    join_clause = _build_join(left_table, right_table, left_alias, right_alias, fk_relations)

    select_columns = [f"{left_alias}.[id]"]
    if left_table == "t_jobs" and "jobNumber" in schema[left_table]:
        select_columns.append(f"{left_alias}.[jobNumber]")
    if "createdAt" in schema[left_table]:
        select_columns.append(f"{left_alias}.[createdAt]")

    if right_table == "t_allocations":
        select_columns.append(f"{right_alias}.[id] AS [allocationId]")
    elif right_table == "t_reminders":
        select_columns.append(f"{right_alias}.[id] AS [reminderId]")
    elif right_table == "t_work-orders":
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