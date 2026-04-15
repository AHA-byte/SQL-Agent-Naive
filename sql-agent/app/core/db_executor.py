from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text

from app.config import DatabaseConfig
from app.core.errors import ServiceError
from app.core.sql_validator import enforce_row_limit, validate_read_only_sql


def get_engine(db_config: DatabaseConfig):
    if db_config.user:
        uid = db_config.user
        if "@" not in uid and "." in db_config.host:
            server_prefix = db_config.host.split(".", 1)[0]
            uid = f"{uid}@{server_prefix}"
        conn_str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server=tcp:{db_config.host},{db_config.port};"
            f"Database={db_config.db};"
            f"UID={uid};"
            f"PWD={db_config.password or ''};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )
        url = f"mssql+pyodbc:///?odbc_connect={quote_plus(conn_str)}"
    else:
        auth_mode = (db_config.auth_mode or "ActiveDirectoryMsi").strip()
        uid_segment = f"UID={db_config.msi_client_id};" if db_config.msi_client_id else ""
        conn_str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server=tcp:{db_config.host},{db_config.port};"
            f"Database={db_config.db};"
            f"Authentication={auth_mode};"
            f"{uid_segment}"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )
        url = f"mssql+pyodbc:///?odbc_connect={quote_plus(conn_str)}"
    return create_engine(url, pool_pre_ping=True)


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def execute_read_only_query(
    db_config: DatabaseConfig,
    sql: str,
    allowed_tables: set[str] | None,
    allowed_columns_by_table: dict[str, set[str]] | None,
    allowed_schemas: set[str] | None,
    max_rows: int = 500,
    validated: bool = False,
) -> pd.DataFrame:
    if not validated:
        validate_read_only_sql(
            sql,
            allowed_tables=allowed_tables,
            allowed_columns_by_table=allowed_columns_by_table,
            allowed_schemas=allowed_schemas,
        )
    wrapped_sql = enforce_row_limit(sql, max_rows=max_rows)

    engine = get_engine(db_config)
    with engine.connect() as conn:
        result = conn.execute(text(wrapped_sql))
        return pd.DataFrame(result.fetchall(), columns=result.keys())


def preview_table(db_config: DatabaseConfig, table_name: str, limit: int = 20) -> pd.DataFrame:
    if limit <= 0 or limit > 1000:
        raise ServiceError("limit must be between 1 and 1000")
    query = text(f"SELECT TOP {limit} * FROM [{table_name}]")
    engine = get_engine(db_config)
    with engine.connect() as conn:
        result = conn.execute(query)
        return pd.DataFrame(result.fetchall(), columns=result.keys())
