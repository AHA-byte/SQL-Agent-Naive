import os
from typing import Dict, List, Tuple
from dataclasses import dataclass
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def mysql_url(db: str | None = None) -> str:
    host = os.getenv("MYSQL_HOST","127.0.0.1")
    port = int(os.getenv("MYSQL_PORT","3306"))
    user = os.getenv("MYSQL_USER","root")
    pwd  = os.getenv("MYSQL_PASSWORD","")
    if db:
        return f"mysql+mysqlconnector://{user}:{pwd}@{host}:{port}/{db}"
    else:
        return f"mysql+mysqlconnector://{user}:{pwd}@{host}:{port}"

@dataclass
class TableInfo:
    schema: str
    name: str
    # (column, data_type, is_nullable, column_key, extra)
    columns: List[Tuple[str, str, bool, str | None, str | None]]
    primary_key: List[str]
    # (col, ref_schema, ref_table, ref_col)
    fks: List[Tuple[str, str, str, str]]

def list_databases() -> List[str]:
    eng = create_engine(mysql_url())
    with eng.connect() as c:
        rows = c.execute(text("SHOW DATABASES;")).fetchall()
    return [r[0] for r in rows if r[0] not in ("information_schema","mysql","performance_schema","sys")]

def get_schema_tables(schema: str) -> List[str]:
    eng = create_engine(mysql_url(schema))
    with eng.connect() as c:
        rows = c.execute(text("SHOW FULL TABLES WHERE Table_type='BASE TABLE';")).fetchall()
    return [r[0] for r in rows]

def load_table_info(schema: str, table: str) -> TableInfo:
    eng = create_engine(mysql_url(schema))
    with eng.connect() as c:
        cols = c.execute(text("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, EXTRA
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
            ORDER BY ORDINAL_POSITION
        """), {"schema": schema, "table": table}).fetchall()

        pk = c.execute(text("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND CONSTRAINT_NAME='PRIMARY'
            ORDER BY ORDINAL_POSITION
        """), {"schema": schema, "table": table}).fetchall()
        pk_cols = [r[0] for r in pk]

        fks = c.execute(text("""
            SELECT kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_SCHEMA, kcu.REFERENCED_TABLE_NAME, kcu.REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            WHERE kcu.TABLE_SCHEMA = :schema AND kcu.TABLE_NAME = :table
              AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
        """), {"schema": schema, "table": table}).fetchall()

    columns = [(r[0], r[1], r[2]=="YES", r[3], r[4]) for r in cols]
    fk_list = [(r[0], r[1], r[2], r[3]) for r in fks]
    return TableInfo(schema=schema, name=table, columns=columns, primary_key=pk_cols, fks=fk_list)

def dependency_order(schema: str, tables: List[str]) -> List[str]:
    """
    Return tables in parent->child order using FK relationships.
    If T has FK to P, then P appears before T.
    """
    infos = {t: load_table_info(schema, t) for t in tables}
    # Build graph: parent -> set(children)
    graph: Dict[str, set] = {t:set() for t in tables}
    indeg: Dict[str, int] = {t:0 for t in tables}

    for t, info in infos.items():
        # for each FK (col -> ref_table), t depends on ref_table
        for (_, ref_schema, ref_table, _) in info.fks:
            if ref_schema == schema and ref_table in graph:
                # edge: ref_table (parent) -> t (child)
                if t not in graph[ref_table]:
                    graph[ref_table].add(t)
                    indeg[t] += 1

    # Kahn's algorithm
    queue = [t for t,d in indeg.items() if d == 0]
    order: List[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for child in graph[n]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)

    # fallback if cycle: append any missing
    for t in tables:
        if t not in order:
            order.append(t)
    return order
