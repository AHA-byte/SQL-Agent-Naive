import re
from urllib.parse import quote_plus

import pandas as pd
from openai import OpenAI
from sqlalchemy import create_engine, text

from app.config import DatabaseConfig, get_available_databases, get_openai_settings

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


class ServiceError(Exception):
    pass


def get_db_config_or_raise(database_name: str) -> DatabaseConfig:
    dbs = get_available_databases()
    if not dbs:
        raise ServiceError("No valid database configuration found in environment variables")
    if database_name not in dbs:
        raise ServiceError(f"Unknown database '{database_name}'")
    return dbs[database_name]


def get_engine(db_config: DatabaseConfig):
    password = quote_plus(db_config.password)
    url = (
        f"mssql+pyodbc://{db_config.user}:{password}@{db_config.host}:{db_config.port}/{db_config.db}"
        "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
    )
    return create_engine(url, pool_pre_ping=True)


def list_tables(database_name: str) -> list[str]:
    config = get_db_config_or_raise(database_name)
    engine = get_engine(config)
    query = text(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()
    return [row[0] for row in rows]


def fetch_schema(database_name: str) -> dict[str, list[str]]:
    config = get_db_config_or_raise(database_name)
    engine = get_engine(config)
    table_query = text(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
        """
    )
    col_query = text(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = :table_name
        ORDER BY ORDINAL_POSITION
        """
    )

    schema_dict: dict[str, list[str]] = {}
    with engine.connect() as conn:
        tables = conn.execute(table_query).fetchall()
        for t in tables:
            table_name = t[0]
            cols = conn.execute(col_query, {"table_name": table_name}).fetchall()
            schema_dict[table_name] = [c[0] for c in cols]
    return schema_dict


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def fetch_table_data(database_name: str, table_name: str, limit: int = 20) -> pd.DataFrame:
    if limit <= 0 or limit > 1000:
        raise ServiceError("limit must be between 1 and 1000")

    if not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
        raise ServiceError("Invalid table name")

    config = get_db_config_or_raise(database_name)
    engine = get_engine(config)
    query = text(f"SELECT TOP {limit} * FROM [{table_name}]")
    with engine.connect() as conn:
        result = conn.execute(query)
        return pd.DataFrame(result.fetchall(), columns=result.keys())


def format_schema_for_prompt(schema: dict[str, list[str]]) -> str:
    return "\n".join([f"{table}: {', '.join(columns)}" for table, columns in schema.items()])


def generate_sql(user_query: str, schema_text: str) -> str:
    if not user_query.strip():
        raise ServiceError("user_query is required")
    if not schema_text.strip():
        raise ServiceError("schema_text is required")

    api_key, model = get_openai_settings()
    if not api_key:
        raise ServiceError("OPENAI_API_KEY is missing")

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are a world-class T-SQL (SQL Server) expert who translates natural language to SQL.
Based on the following database schema, write a valid T-SQL query to answer the user's request.

Database Schema:
---
{schema_text}
---

User Query: \"{user_query}\"

IMPORTANT RULES:
- Use square brackets [table_name] and [column_name] for identifiers
- Use TOP n instead of LIMIT n
- Return only the SQL query, no markdown formatting

T-SQL Query:
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are an expert T-SQL/SQL Server query generator. Always use square brackets for identifiers and TOP for limiting rows. Return only raw SQL without markdown.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    sql = response.choices[0].message.content or ""
    return sql.replace("```sql", "").replace("```", "").strip()


def validate_read_only_sql(sql: str) -> None:
    if not sql or not sql.strip():
        raise ServiceError("SQL query is empty")

    normalized = re.sub(r"\s+", " ", sql.strip()).lower()

    if ";" in normalized[:-1]:
        raise ServiceError("Only single statement SQL is allowed")

    if not (normalized.startswith("select ") or normalized.startswith("with ")):
        raise ServiceError("Only SELECT queries are allowed")

    tokenized = re.findall(r"[a-zA-Z_]+", normalized)
    blocked = sorted({t for t in tokenized if t in BLOCKED_SQL_KEYWORDS})
    if blocked:
        raise ServiceError(f"Blocked SQL keyword(s) detected: {', '.join(blocked)}")


def execute_query(database_name: str, sql: str, max_rows: int = 1000) -> pd.DataFrame:
    validate_read_only_sql(sql)

    config = get_db_config_or_raise(database_name)
    engine = get_engine(config)

    safe_sql = sql.strip().rstrip(";")
    wrapped_sql = f"SELECT TOP {max_rows} * FROM ({safe_sql}) AS q"

    with engine.connect() as conn:
        result = conn.execute(text(wrapped_sql))
        return pd.DataFrame(result.fetchall(), columns=result.keys())
