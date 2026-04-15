import pandas as pd

from app.config import get_allowed_schemas
from app.core.db_executor import execute_read_only_query, preview_table
from app.core.errors import ServiceError
from app.core.prompt_builder import (
    format_fk_for_prompt,
    format_schema_for_prompt,
)
from app.core.schema_loader import fetch_foreign_keys, fetch_schema, get_db_config_or_raise
from app.core.sql_generator import generate_sql
from app.core.sql_validator import validate_read_only_sql


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def fetch_table_data(database_name: str, table_name: str, limit: int = 20) -> pd.DataFrame:
    _, config = get_db_config_or_raise(database_name)
    return preview_table(config, table_name=table_name, limit=limit)


def execute_query(database_name: str, sql: str, max_rows: int = 1000) -> pd.DataFrame:
    _, config = get_db_config_or_raise(database_name)
    schema = fetch_schema(database_name)
    allowed_tables = {table.lower() for table in schema.keys()}
    allowed_columns_by_table = {
        table.lower(): {column.lower() for column in columns}
        for table, columns in schema.items()
    }
    allowed_schemas = get_allowed_schemas()
    return execute_read_only_query(
        db_config=config,
        sql=sql,
        allowed_tables=allowed_tables,
        allowed_columns_by_table=allowed_columns_by_table,
        allowed_schemas=allowed_schemas,
        max_rows=max_rows,
        validated=False,
    )


def list_tables(database_name: str) -> list[str]:
    return sorted(fetch_schema(database_name).keys())
