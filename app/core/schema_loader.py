import re

from sqlalchemy import text

from app.config import DatabaseConfig, get_available_databases, get_default_database_name
from app.core.errors import ServiceError
from app.core.prompt_builder import format_fk_for_prompt, format_schema_for_prompt
from app.core.db_executor import get_engine


def get_db_config_or_raise(database_name: str | None) -> tuple[str, DatabaseConfig]:
    dbs = get_available_databases()
    if not dbs:
        raise ServiceError("No valid database configuration found in environment variables")

    chosen = database_name or get_default_database_name(dbs)
    if not chosen:
        raise ServiceError("database is required and no default database is configured")

    if chosen not in dbs:
        raise ServiceError(f"Unknown database '{chosen}'")

    return chosen, dbs[chosen]

def fetch_table_names(database_name: str) -> list[str]:
    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)

    table_query = text(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_NAME
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(table_query).fetchall()

    return [row[0] for row in rows]


def fetch_schema(database_name: str, table_filter: list[str] | None = None) -> dict[str, list[str]]:
    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)

    col_query = text(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = :table_name AND TABLE_SCHEMA = 'dbo'
        ORDER BY ORDINAL_POSITION
        """
    )

    schema_dict: dict[str, list[str]] = {}
    selected_tables = table_filter or fetch_table_names(database_name)
    with engine.connect() as conn:
        for table_name in selected_tables:
            cols = conn.execute(col_query, {"table_name": table_name}).fetchall()
            schema_dict[table_name] = [c[0] for c in cols]
    return schema_dict


def fetch_foreign_keys(database_name: str, table_filter: set[str] | None = None) -> list[dict]:
    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)

    fk_query = text(
        """
        SELECT
            fk.name AS fk_name,
            s1.name AS parent_schema,
            tp.name AS parent_table,
            cp.name AS parent_column,
            s2.name AS referenced_schema,
            tr.name AS referenced_table,
            cr.name AS referenced_column
        FROM sys.foreign_keys AS fk
        JOIN sys.foreign_key_columns AS fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables AS tp ON fkc.parent_object_id = tp.object_id
        JOIN sys.schemas AS s1 ON tp.schema_id = s1.schema_id
        JOIN sys.columns AS cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
        JOIN sys.tables AS tr ON fkc.referenced_object_id = tr.object_id
        JOIN sys.schemas AS s2 ON tr.schema_id = s2.schema_id
        JOIN sys.columns AS cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
        WHERE s1.name = 'dbo' AND s2.name = 'dbo'
        ORDER BY tp.name, tr.name
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(fk_query).fetchall()

    all_fks = [
        {
            "fk_name": r[0],
            "parent_schema": r[1],
            "parent_table": r[2],
            "parent_column": r[3],
            "referenced_schema": r[4],
            "referenced_table": r[5],
            "referenced_column": r[6],
        }
        for r in rows
    ]

    if not table_filter:
        return all_fks

    return [
        fk
        for fk in all_fks
        if fk["parent_table"] in table_filter and fk["referenced_table"] in table_filter
    ]


def _tokenize_message(message: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", message.lower()))


def _score_table(table: str, columns: list[str], tokens: set[str]) -> int:
    score = 0
    table_tokens = set(re.findall(r"[a-zA-Z0-9_]+", table.lower()))
    score += len(table_tokens.intersection(tokens)) * 3
    for col in columns:
        col_tokens = set(re.findall(r"[a-zA-Z0-9_]+", col.lower()))
        score += len(col_tokens.intersection(tokens))
    return score


def _score_table_name_only(table: str, tokens: set[str]) -> int:
    table_tokens = set(re.findall(r"[a-zA-Z0-9_]+", table.lower()))
    return len(table_tokens.intersection(tokens))


def _intent_tables_from_message(user_message: str) -> set[str]:
    q = (user_message or "").lower()
    intent_tables: set[str] = set()

    if "job" in q:
        intent_tables.add("t_jobs")
    if "allocation" in q:
        intent_tables.add("t_allocations")
    if "reminder" in q:
        intent_tables.add("t_reminders")
    if "work order" in q or "work-order" in q:
        intent_tables.add("t_work-orders")

    return intent_tables


def select_relevant_table_names(table_names: list[str], user_message: str, max_tables: int = 12) -> list[str]:
    if len(table_names) <= max_tables:
        return sorted(table_names)

    tokens = _tokenize_message(user_message)
    ranked = sorted(
        table_names,
        key=lambda table_name: (_score_table_name_only(table_name, tokens), table_name),
        reverse=True,
    )
    intent_tables = [table for table in _intent_tables_from_message(user_message) if table in table_names]

    # Put intent tables first, then fill remaining slots by ranking.
    prioritized = intent_tables + ranked
    selected = list(dict.fromkeys(prioritized))
    return selected[:max_tables]


def select_relevant_schema_subset(
    full_schema: dict[str, list[str]],
    foreign_keys: list[dict],
    user_message: str,
    max_tables: int = 12,
) -> tuple[dict[str, list[str]], list[dict]]:
    if len(full_schema) <= max_tables:
        return full_schema, foreign_keys

    tokens = _tokenize_message(user_message)
    ranked = sorted(
        full_schema.items(),
        key=lambda item: (_score_table(item[0], item[1], tokens), item[0]),
        reverse=True,
    )

    selected_tables = [t for t, _ in ranked[:max_tables]]
    selected_set = set(selected_tables)
    selected_schema = {table: full_schema[table] for table in selected_tables}

    selected_fk = [
        fk
        for fk in foreign_keys
        if fk["parent_table"] in selected_set and fk["referenced_table"] in selected_set
    ]

    return selected_schema, selected_fk


def load_schema_context(database_name: str | None, user_message: str, max_tables: int = 12) -> dict:
    chosen_db, _ = get_db_config_or_raise(database_name)
    candidate_table_names = fetch_table_names(chosen_db)
    selected_tables = select_relevant_table_names(
        candidate_table_names,
        user_message=user_message,
        max_tables=max_tables,
    )
    selected_schema = fetch_schema(chosen_db, table_filter=selected_tables)
    selected_fk = fetch_foreign_keys(chosen_db, table_filter=set(selected_tables))

    return {
        "database": chosen_db,
        "schema": selected_schema,
        "schema_text": format_schema_for_prompt(selected_schema),
        "foreign_keys": selected_fk,
        "fk_text": format_fk_for_prompt(selected_fk),
    }
