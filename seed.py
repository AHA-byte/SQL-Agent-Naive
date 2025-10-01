import os, argparse, json, random
from typing import Dict, List
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
from schema_introspect import get_schema_tables, load_table_info, dependency_order, mysql_url
from faker_factories import value_for, fix_enum, reset_uniques

load_dotenv()

def get_engine(db: str | None) -> Engine:
    return create_engine(mysql_url(db))

def detect_enum_options(conn, schema: str, table: str, column: str):
    row = conn.execute(text("""
        SELECT COLUMN_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t AND COLUMN_NAME=:c
    """), {"s": schema, "t": table, "c": column}).scalar()
    if row and row.lower().startswith("enum("):
        inside = row[row.find("(")+1:row.rfind(")")]
        return [x.strip().strip("'").strip('"') for x in inside.split(",")]
    return None

def truncate_table(conn, schema: str, table: str):
    conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
    conn.execute(text(f"TRUNCATE TABLE `{schema}`.`{table}`;"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))

_fk_cache: Dict[tuple, List] = {}

def sample_fk_value(conn, ref_schema: str, ref_table: str, ref_col: str):
    key = (ref_schema, ref_table, ref_col)
    vals = _fk_cache.get(key)
    if not vals:
        rows = conn.execute(text(f"SELECT `{ref_col}` FROM `{ref_schema}`.`{ref_table}` ORDER BY `{ref_col}` LIMIT 1000")).fetchall()
        vals = [r[0] for r in rows]
        _fk_cache[key] = vals
    if not vals:
        return None
    return random.choice(vals)

def seed_table(conn, schema: str, table: str, nrows: int):
    info = load_table_info(schema, table)

    # Identify AUTO_INCREMENT PKs and UNIQUE columns
    ai_cols = {c for (c, t, _, key, extra) in info.columns if extra and "auto_increment" in (extra or "").lower()}
    unique_cols = {c for (c, t, _, key, extra) in info.columns if (key or "").upper() == "UNI"}

    # FK mapping: column -> (ref_schema, ref_table, ref_col)
    fk_map = {col: (rs, rt, rc) for (col, rs, rt, rc) in info.fks}

    # Columns to insert (skip AI PKs)
    insert_cols = []
    col_types = {}
    enum_map = {}
    for (c, t, _, _, _) in info.columns:
        col_types[c] = t
        if c in ai_cols:
            continue
        insert_cols.append(c)

    # Precompute ENUM options
    for c in insert_cols:
        opts = detect_enum_options(conn, schema, table, c)
        if opts:
            enum_map[c] = opts

    inserted = 0
    for _ in range(nrows):
        row = {}
        for c in insert_cols:
            # FK: sample existing parent id
            if c in fk_map:
                rs, rt, rc = fk_map[c]
                v = sample_fk_value(conn, rs or schema, rt, rc)
                if v is None:
                    row = None
                    break
                row[c] = v
            else:
                if c in enum_map:
                    row[c] = fix_enum(None, enum_map[c])
                else:
                    row[c] = value_for(c, col_types[c], unique=(c in unique_cols), table=table)
        if row is None:
            continue

        cols = ", ".join([f"`{c}`" for c in insert_cols])
        placeholders = ", ".join([f":{c}" for c in insert_cols])
        sql = f"INSERT INTO `{schema}`.`{table}` ({cols}) VALUES ({placeholders})"
        conn.execute(text(sql), row)
        inserted += 1
    return inserted

def main():
    ap = argparse.ArgumentParser(description="MySQL fake data seeder (FK/AI/UNI-safe)")
    ap.add_argument("--schema", required=True, help="Target schema (database)")
    ap.add_argument("--table", help="Specific table (optional)")
    ap.add_argument("--rows", type=int, default=200, help="Rows per table (default 200)")
    ap.add_argument("--truncate", action="store_true", help="Truncate table(s) before insert")
    ap.add_argument("--dry-run", action="store_true", help="Only show dependency order plan, no inserts")
    args = ap.parse_args()

    engine = get_engine(None)
    with engine.begin() as conn:
        tables = [args.table] if args.table else get_schema_tables(args.schema)
        order = dependency_order(args.schema, tables)

        print("Plan (parents before children):")
        print(json.dumps({"schema": args.schema, "tables_in_order": order}, indent=2))

        if args.dry_run:
            return

        if args.truncate:
            for t in order:
                truncate_table(conn, args.schema, t)
            # Clear caches after destructive ops
            reset_uniques()
            _fk_cache.clear()

        for t in order:
            count = seed_table(conn, args.schema, t, args.rows)
            print(f"[{args.schema}.{t}] inserted {count} rows")

if __name__ == "__main__":
    main()
