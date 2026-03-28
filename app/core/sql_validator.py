import re

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


def _extract_tables(sql: str) -> list[tuple[str | None, str]]:
    table_refs: list[tuple[str | None, str]] = []

    schema_table_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<schema>[A-Za-z0-9_]+)\]\s*\.\s*\[(?P<table>[A-Za-z0-9_]+)\]",
        flags=re.IGNORECASE,
    )
    table_only_pattern = re.compile(
        r"\b(?:from|join)\s+\[(?P<table>[A-Za-z0-9_]+)\]",
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

    relationship_hint = any(
        token in query_text
        for token in [
            " with ",
            " related ",
            " relationship",
            "relationships",
            "joined",
            "join",
        ]
    )

    requires_join = len(mentioned_entities) >= 2 or relationship_hint
    if requires_join and " join " not in f" {normalized_sql} ":
        raise ServiceError(
            "JOIN required for relationship query; use foreign-key-based JOINs instead of simple filtering"
        )

    table_refs = _extract_tables(sql)
    table_names = {table for _, table in table_refs}

    expected_relationships = [
        (
            {"jobs", "allocations"},
            {"t_jobs", "t_allocations"},
            ("jobid", "id"),
        ),
        (
            {"jobs", "reminders"},
            {"t_jobs", "t_reminders"},
            ("jobid", "id"),
        ),
        (
            {"jobs", "work_orders"},
            {"t_jobs", "t_work-orders"},
            ("jobid", "id"),
        ),
    ]

    for intent_entities, required_tables, fk_cues in expected_relationships:
        if intent_entities.issubset(mentioned_entities):
            if not required_tables.issubset(table_names):
                required_csv = ", ".join(sorted(required_tables))
                raise ServiceError(
                    f"Relationship query must join expected tables: {required_csv}"
                )
            for cue in fk_cues:
                if cue not in normalized_sql:
                    raise ServiceError(
                        "Relationship query must use foreign-key join columns (for example, jobId and id)"
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
        if schema and schema.lower() not in allowed_schemas:
            raise ServiceError(f"Schema '{schema}' is not allowed")
        if allowed_tables is not None and table.lower() not in allowed_tables:
            raise ServiceError(f"Table '{table}' is not in the allowed schema subset")

    if allowed_columns_by_table:
        col_refs = re.findall(
            r"\[(?P<table>[A-Za-z0-9_]+)\]\s*\.\s*\[(?P<column>[A-Za-z0-9_]+)\]",
            sql,
            flags=re.IGNORECASE,
        )
        for table, column in col_refs:
            table_key = table.lower()
            column_key = column.lower()

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
    return f"SELECT TOP {max_rows} * FROM ({safe_sql}) AS q"


def sanitize_sql(sql: str) -> str:
    reserved_columns = ["start", "end"]

    sanitized = sql
    for col in reserved_columns:
        sanitized = re.sub(rf"(?i)(?<!\[)\b{col}\b(?!\])\s*,", f"[{col}],", sanitized)
        sanitized = re.sub(rf"(?i)(?<!\[)\b{col}\b(?!\])", f"[{col}]", sanitized)

    # Bracket hyphenated table names in FROM/JOIN clauses (e.g., t_work-orders).
    sanitized = re.sub(
        r"(?i)\b(from|join)\s+([A-Za-z_][A-Za-z0-9_]*-[A-Za-z0-9_-]*)\b",
        lambda m: f"{m.group(1)} [{m.group(2)}]",
        sanitized,
    )

    return sanitized
