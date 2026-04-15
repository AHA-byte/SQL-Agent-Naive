import re

from app.core.business_safety import is_system_or_internal_identifier
from app.core.errors import ServiceError

BLOCKED_SQL_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "drop",
    "alter",
    "truncate",
    "create",
    "exec",
    "execute",
}

BLOCKED_PATTERNS = [
    r"--",          # Inline comments
    r"/\*",         # Block comments
    r"\bxp_[a-z0-9_]*\b",
    r"\bsp_[a-z0-9_]*\b",
    r"\bsys\.",
]


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip()).lower()


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _table_matches_concept(table_name: str, concept: str) -> bool:
    normalized = _normalize_identifier(table_name)
    if concept == "jobs":
        return "job" in normalized
    if concept == "allocations":
        return "alloc" in normalized
    if concept == "reminders":
        return "remind" in normalized
    if concept == "work_orders":
        return "workorder" in normalized
    return False


def _extract_tables(sql: str) -> list[tuple[str | None, str]]:
    table_refs: list[tuple[str | None, str]] = []

    schema_table_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<schema>[A-Za-z0-9_-]+)\]\s*\.\s*\[(?P<table>[A-Za-z0-9_-]+)\]",
        flags=re.IGNORECASE,
    )
    table_only_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<table>[A-Za-z0-9_-]+)\]",
        flags=re.IGNORECASE,
    )

    for match in schema_table_pattern.finditer(sql):
        schema = match.group("schema")
        table = match.group("table")
        table_refs.append((schema.lower(), table.lower()))

    if not table_refs:
        for match in table_only_pattern.finditer(sql):
            table = match.group("table")
            table_refs.append((None, table.lower()))

    return table_refs


def _extract_table_aliases(sql: str) -> dict[str, str]:
    aliases: dict[str, str] = {}

    schema_table_alias_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<schema>[A-Za-z0-9_-]+)\]\s*\.\s*\[(?P<table>[A-Za-z0-9_-]+)\]\s+(?:as\s+)?(?:\[(?P<alias_b>[A-Za-z0-9_-]+)\]|(?P<alias_u>[A-Za-z_][A-Za-z0-9_]*))",
        flags=re.IGNORECASE,
    )
    table_alias_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<table>[A-Za-z0-9_-]+)\]\s+(?:as\s+)?(?:\[(?P<alias_b>[A-Za-z0-9_-]+)\]|(?P<alias_u>[A-Za-z_][A-Za-z0-9_]*))",
        flags=re.IGNORECASE,
    )

    for match in schema_table_alias_pattern.finditer(sql):
        table = match.group("table").lower()
        alias = (match.group("alias_b") or match.group("alias_u") or "").lower()
        if alias:
            aliases[alias] = table

    for match in table_alias_pattern.finditer(sql):
        table = match.group("table").lower()
        alias = (match.group("alias_b") or match.group("alias_u") or "").lower()
        if alias and alias not in aliases:
            aliases[alias] = table

    return aliases


def validate_sql(query: str):
    normalized = _normalize_sql(query)
    tokens = set(re.findall(r"[a-zA-Z_]+", normalized))
    write_keywords = {"insert", "update", "delete", "drop", "alter", "merge", "truncate", "create"}

    if tokens.intersection(write_keywords):
        raise ValueError("Only read queries allowed")

    if "select *" in normalized:
        raise ValueError("SELECT * is forbidden")

    if " top " not in f" {normalized} ":
        raise ValueError("TOP required")

    return query


def validate_join_requirements(user_query: str, sql: str) -> None:
    query_text = (user_query or "").lower()
    normalized_sql = _normalize_sql(sql)

    if not query_text:
        return

    # Status-history requests often join through objectId/objectType rather than jobId token patterns.
    if "status history" in query_text and "allocation" in query_text:
        return

    entity_keywords = {
        "jobs": ["job", "jobs"],
        "allocations": ["allocation", "allocations"],
        "reminders": ["reminder", "reminders"],
        "work_orders": ["work order", "work orders", "work-order", "work-orders"],
    }

    mentioned_entities = {
        name
        for name, terms in entity_keywords.items()
        if any(term in query_text for term in terms)
    }

    # Require JOIN only when multiple known entities are requested.
    # Natural language phrases like "with SOW" should not force JOIN logic.
    requires_join = len(mentioned_entities) >= 2
    if requires_join and " join " not in f" {normalized_sql} ":
        raise ServiceError(
            "JOIN required for relationship query; use foreign-key-based JOINs instead of simple filtering"
        )

    table_refs = _extract_tables(sql)
    table_names = {table for _, table in table_refs}

    expected_relationships = [
        ({"jobs", "allocations"}, ("jobs", "allocations"), "jobid"),
        ({"jobs", "reminders"}, ("jobs", "reminders"), "jobid"),
        ({"jobs", "work_orders"}, ("jobs", "work_orders"), "jobid"),
    ]

    for intent_entities, required_concepts, fk_column in expected_relationships:
        if intent_entities.issubset(mentioned_entities):
            concept_presence = {
                concept: any(_table_matches_concept(table_name, concept) for table_name in table_names)
                for concept in required_concepts
            }
            if not all(concept_presence.values()):
                required_csv = ", ".join(required_concepts)
                raise ServiceError(
                    f"Relationship query must join expected table concepts: {required_csv}"
                )

            if not re.search(rf"\b{re.escape(fk_column)}\b", normalized_sql):
                raise ServiceError(
                    f"Relationship query must reference the foreign key column '{fk_column}'"
                )


def validate_read_only_sql(
    sql: str,
    allowed_tables: set[str] | None = None,
    allowed_columns_by_table: dict[str, set[str]] | None = None,
    allowed_schemas: set[str] | None = None,
) -> None:
    if not sql or not sql.strip():
        raise ServiceError("SQL query is empty")

    try:
        validate_sql(sql)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc

    normalized = _normalize_sql(sql)

    if ";" in normalized[:-1]:
        raise ServiceError("Only single statement SQL is allowed")

    if not (normalized.startswith("select ") or normalized.startswith("with ")):
        raise ServiceError("Only SELECT queries are allowed")

    tokenized = re.findall(r"[a-zA-Z_]+", normalized)
    if blocked := sorted({t for t in tokenized if t in BLOCKED_SQL_KEYWORDS}):
        raise ServiceError(f"Blocked SQL keyword(s) detected: {', '.join(blocked)}")

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, normalized):
            raise ServiceError("Blocked SQL pattern detected")

    if " top " not in f" {normalized} " and " limit " not in f" {normalized} ":
        raise ServiceError("SQL must include TOP n or LIMIT n")

    if allowed_schemas is None:
        allowed_schemas = {"dbo"}

    table_refs = _extract_tables(sql)
    for schema, table in table_refs:
        table_identifier = f"{schema}.{table}" if schema else table
        if is_system_or_internal_identifier(table_identifier):
            raise ServiceError(f"Table '{table_identifier}' is blocked as system/internal metadata")
        if schema and schema.lower() not in allowed_schemas:
            raise ServiceError(f"Schema '{schema}' is not allowed")
        if allowed_tables is not None and table.lower() not in allowed_tables:
            raise ServiceError(f"Table '{table}' is not in the allowed schema subset")

    if allowed_columns_by_table:
        alias_to_table = _extract_table_aliases(sql)
        col_refs = re.findall(
            r"\[(?P<table>[A-Za-z0-9_-]+)\]\s*\.\s*\[(?P<column>[A-Za-z0-9_-]+)\]",
            sql,
            flags=re.IGNORECASE,
        )
        for table, column in col_refs:
            table_key = table.lower()
            column_key = column.lower()

            # Resolve alias-qualified references such as [j].[id] to their source table.
            if table_key not in allowed_columns_by_table and table_key in alias_to_table:
                table_key = alias_to_table[table_key]

            # Skip schema-qualified table references like [dbo].[orders]
            if allowed_schemas and table_key in allowed_schemas and allowed_tables and column_key in allowed_tables:
                continue

            if table_key not in allowed_columns_by_table:
                raise ServiceError(f"Table '{table}' is not in the allowed schema subset")
            if column_key not in allowed_columns_by_table[table_key]:
                raise ServiceError(f"Column '{column}' is not allowed for table '{table}'")


def enforce_row_limit(sql: str, max_rows: int = 500) -> str:
    if max_rows <= 0 or max_rows > 5000:
        raise ServiceError("max_rows must be between 1 and 5000")

    safe_sql = sql.strip().rstrip(";")

    # Insert or clamp TOP on the outer SELECT instead of wrapping as SELECT * FROM (...).
    upper_sql = safe_sql.upper()
    select_idx = upper_sql.find("SELECT")
    if select_idx < 0:
        return f"SELECT TOP {max_rows} * FROM ({safe_sql}) AS _row_limit_q"

    after_select = safe_sql[select_idx + len("SELECT"):]
    top_match = re.match(r"\s+TOP\s+(\d+)", after_select, re.IGNORECASE)
    if top_match:
        existing_top = int(top_match.group(1))
        effective_top = min(existing_top, max_rows)
        replaced = re.sub(
            r"(\s+TOP\s+)\d+",
            lambda m: f"{m.group(1)}{effective_top}",
            after_select,
            count=1,
            flags=re.IGNORECASE,
        )
        return safe_sql[:select_idx + len("SELECT")] + replaced

    leading_ws = re.match(r"(\s+)", after_select)
    separator = leading_ws.group(1) if leading_ws else " "
    rest = after_select.lstrip()
    return safe_sql[:select_idx + len("SELECT")] + separator + f"TOP {max_rows} " + rest


def sanitize_sql(sql: str) -> str:
    sanitized = sql

    # Normalize 3-part identifiers [database].[schema].[table] to [schema].[table].
    sanitized = re.sub(
        r"\[(?P<db>[A-Za-z0-9_-]+)\]\s*\.\s*\[(?P<schema>[A-Za-z0-9_-]+)\]\s*\.\s*\[(?P<table>[A-Za-z0-9_-]+)\]",
        lambda m: f"[{m.group('schema')}].[{m.group('table')}]",
        sanitized,
        flags=re.IGNORECASE,
    )

    sanitized = re.sub(
        r"(?i)\b(from|join)\s+([A-Za-z0-9_]+)\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)",
        lambda m: f"{m.group(1)} [{m.group(3)}].[{m.group(4)}]",
        sanitized,
    )

    # Bracket hyphenated table names in FROM/JOIN clauses (e.g., t_work-orders).
    sanitized = re.sub(
        r"(?i)\b(from|join)\s+([A-Za-z_][A-Za-z0-9_]*-[A-Za-z0-9_-]*)\b",
        lambda m: f"{m.group(1)} [{m.group(2)}]",
        sanitized,
    )

    return sanitized
