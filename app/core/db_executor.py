from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text

from app.config import DatabaseConfig
from app.core.errors import ServiceError
from app.core.sql_validator import enforce_row_limit, validate_read_only_sql


def get_engine(db_config: DatabaseConfig):
    password = quote_plus(db_config.password)
    url = (
        f"mssql+pyodbc://{db_config.user}:{password}@{db_config.host}:{db_config.port}/{db_config.db}"
        "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
    )
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
) -> pd.DataFrame:
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
