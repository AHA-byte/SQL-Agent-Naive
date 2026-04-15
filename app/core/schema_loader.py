import re
import time

from sqlalchemy import text

from app.config import (
    DatabaseConfig,
    get_allowed_schemas,
    get_available_databases,
    get_default_database_name,
    get_schema_cache_ttl,
)
from app.core.business_safety import filter_business_table_candidates, is_system_or_internal_identifier
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


_TABLE_CACHE: dict[str, tuple[float, list[str]]] = {}
_SCHEMA_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, list[str]]]] = {}
_FK_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _get_cached(cache: dict, key, ttl_seconds: int):
    if key in cache:
        timestamp, value = cache[key]
        if time.time() - timestamp <= ttl_seconds:
            return value
        cache.pop(key, None)
    return None


def _set_cached(cache: dict, key, value):
    cache[key] = (time.time(), value)


def _table_key(schema: str, table: str) -> str:
    return table if schema.lower() == "dbo" else f"{schema}.{table}"


def _split_table_key(table_key: str) -> tuple[str, str]:
    if "." in table_key:
        schema, table = table_key.split(".", 1)
        return schema, table
    return "dbo", table_key


def fetch_table_names(database_name: str) -> list[str]:
    cache_ttl = get_schema_cache_ttl()
    cached = _get_cached(_TABLE_CACHE, database_name, cache_ttl)
    if cached is not None:
        return cached

    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)
    allowed_schemas = sorted(get_allowed_schemas())
    schema_csv = ", ".join(f"'{schema}'" for schema in allowed_schemas)

    table_query = text(
        f"""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
          AND TABLE_SCHEMA IN ({schema_csv})
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(table_query).fetchall()

    names = [_table_key(str(row[0]), str(row[1])) for row in rows]
    names = sorted(dict.fromkeys(names))
    names = filter_business_table_candidates(database_name, names)
    _set_cached(_TABLE_CACHE, database_name, names)
    return names


def fetch_schema(database_name: str, table_filter: list[str] | None = None) -> dict[str, list[str]]:
    table_filter = table_filter or fetch_table_names(database_name)
    cache_ttl = get_schema_cache_ttl()
    cache_key = (database_name, tuple(sorted(table_filter)))
    cached = _get_cached(_SCHEMA_CACHE, cache_key, cache_ttl)
    if cached is not None:
        return cached

    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)

    col_query = text(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = :table_name AND TABLE_SCHEMA = :table_schema
        ORDER BY ORDINAL_POSITION
        """
    )

    # Date/time types where the LLM might mistakenly use = 0 or = 1
    _TYPED_HINT_TYPES = {"datetime", "datetime2", "date", "datetimeoffset", "smalldatetime", "time"}

    schema_dict: dict[str, list[str]] = {}
    with engine.connect() as conn:
        for table_key in table_filter:
            table_schema, table_name = _split_table_key(table_key)
            cols = conn.execute(
                col_query,
                {
                    "table_name": table_name,
                    "table_schema": table_schema,
                },
            ).fetchall()
            col_list = []
            for col_name, data_type in cols:
                if data_type and data_type.lower() in _TYPED_HINT_TYPES:
                    col_list.append(f"{col_name} ({data_type})")
                else:
                    col_list.append(col_name)
            schema_dict[table_key] = col_list

    _set_cached(_SCHEMA_CACHE, cache_key, schema_dict)
    return schema_dict


def fetch_foreign_keys(database_name: str, table_filter: set[str] | None = None) -> list[dict]:
    cache_ttl = get_schema_cache_ttl()
    if table_filter is None:
        cached = _get_cached(_FK_CACHE, database_name, cache_ttl)
        if cached is not None:
            return cached

    _, config = get_db_config_or_raise(database_name)
    engine = get_engine(config)
    allowed_schemas = sorted(get_allowed_schemas())
    schema_csv = ", ".join(f"'{schema}'" for schema in allowed_schemas)

    fk_query = text(
        f"""
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
        WHERE s1.name IN ({schema_csv}) AND s2.name IN ({schema_csv})
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

    all_fks = [
        fk
        for fk in all_fks
        if not is_system_or_internal_identifier(_table_key(fk["parent_schema"], fk["parent_table"]))
        and not is_system_or_internal_identifier(_table_key(fk["referenced_schema"], fk["referenced_table"]))
    ]

    if not table_filter:
        _set_cached(_FK_CACHE, database_name, all_fks)
        return all_fks

    normalized_filter = {item.lower() for item in table_filter}

    return [
        fk
        for fk in all_fks
        if (
            fk["parent_table"].lower() in normalized_filter
            or _table_key(fk["parent_schema"], fk["parent_table"]).lower() in normalized_filter
        )
        and (
            fk["referenced_table"].lower() in normalized_filter
            or _table_key(fk["referenced_schema"], fk["referenced_table"]).lower() in normalized_filter
        )
    ]


def _tokenize_message(message: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", message.lower()))


# Synonym map: if ANY key word appears in the user query, all value words
# are injected as bonus tokens for scoring. This lets "construction" boost
# tables containing "estimates", "receivable", "statuses" etc. without
# hardcoding table names.
_SYNONYM_EXPANSIONS: dict[str, set[str]] = {
    "construction": {"estimates", "snapshot", "statuses", "receivable", "catastrophe", "histories"},
    "sow": {"estimates", "snapshot", "authorised"},
    "scope": {"estimates", "snapshot"},
    "ar": {"receivable", "invoices", "accounts"},
    "ap": {"payable", "invoices", "accounts"},
    "receivable": {"invoices", "accounts", "ar"},
    "payable": {"invoices", "accounts", "ap"},
    "invoice": {"receivable", "payable", "accounts", "xero"},
    "finance": {"receivable", "payable", "invoices", "accounts", "users"},
    "productivity": {"receivable", "payable", "invoices", "users"},
    "active": {"statuses", "jobs"},
    "stage": {"statuses", "jobs"},
    "open": {"statuses", "allocation"},
    "user": {"users"},
    "by user": {"users"},
    "qbcc": {"policies", "reminders", "estimates", "expense"},
    "policy": {"policies", "qbcc"},
    "premium": {"policies", "qbcc"},
    "brand": {"clients", "reporting", "contacts"},
    "customer": {"contacts", "clients"},
    "client": {"contacts", "clients", "markup"},
    "insurer": {"clients", "contacts", "jobs", "statuses"},
    "markup": {"clients", "markup", "estimates", "snapshot", "contacts"},
    "vulnerable": {"jobs", "notifications", "contacts", "statuses"},
    "won": {"jobs", "statuses", "clients", "contacts"},
    "closed": {"jobs", "statuses", "clients"},
    "active": {"jobs", "statuses", "clients", "contacts"},
    "win rate": {"winrates", "precon"},
    "pending": {"statuses", "histories", "estimates"},
    "band": {"estimates", "snapshot", "catastrophe"},
    "cost": {"payable", "expense", "estimates"},
    "expense": {"expense", "invoices"},
    "complete": {"statuses", "histories"},
    "overdue": {"statuses", "reminders"},
    "status": {"statuses", "histories", "allocation"},
    "history": {"histories", "statuses"},
    "notification": {"notifications"},
    "supplier": {"contacts", "payable"},
    # IN4MO synonyms
    "claim": {"claiminformation", "costcontrol", "workplan", "invoice", "documents", "projectplan", "chatroom"},
    "lodgement": {"claiminformation", "costcontrol"},
    "loss": {"claiminformation", "costcontrol"},
    "coverage": {"claiminformation"},
    "work plan": {"workplan", "claiminformation", "costcontrol"},
    "cost control": {"costcontrol", "claiminformation", "workplan"},
    "project plan": {"projectplan", "claiminformation"},
    "chat": {"chatroom", "claiminformation"},
    "document": {"documents", "claiminformation"},
}


def _expand_tokens_with_synonyms(tokens: set[str]) -> set[str]:
    """Expand user query tokens with domain synonyms for better table scoring."""
    expanded = set(tokens)
    for trigger, synonyms in _SYNONYM_EXPANSIONS.items():
        trigger_words = set(trigger.split())
        if trigger_words.issubset(tokens):
            expanded.update(synonyms)
    return expanded


def _score_table(table: str, columns: list[str], tokens: set[str]) -> int:
    score = 0
    expanded = _expand_tokens_with_synonyms(tokens)
    table_tokens = set(re.findall(r"[a-zA-Z0-9_]+", table.lower()))
    score += len(table_tokens.intersection(expanded)) * 3
    for col in columns:
        col_tokens = set(re.findall(r"[a-zA-Z0-9_]+", col.lower()))
        score += len(col_tokens.intersection(expanded))
    return score


def _score_table_name_only(table: str, tokens: set[str]) -> int:
    expanded = _expand_tokens_with_synonyms(tokens)
    table_tokens = set(re.findall(r"[a-zA-Z0-9_]+", table.lower()))
    return len(table_tokens.intersection(expanded))


def _intent_tables_from_message(user_message: str) -> set[str]:
    q = (user_message or "").lower()
    intent_tables: set[str] = set()

    if "job" in q:
        intent_tables.update({
            "t_jobs",
            "reporting.Jobs",
            "t_contacts",
            "t_statuses",
            "t_status-histories",
            "Clients",
        })
    # "claim" in PRIME context = t_jobs (claims are jobs)
    if "claim" in q:
        intent_tables.update({
            "t_jobs",
            "t_contacts",
            "t_statuses",
            "Clients",
        })
    # Client/insurer queries need the Clients mapping table
    if "client" in q or "insurer" in q or "client group" in q:
        intent_tables.update({
            "Clients",
            "t_contacts",
            "t_jobs",
            "t_statuses",
        })
    if "markup" in q:
        intent_tables.update({
            "Clients-Markup",
            "Clients",
            "t_contacts",
            "t_jobs",
            "t_statuses",
            "t_work-orders",
        })
    if "active" in q:
        intent_tables.update({
            "t_jobs",
            "t_statuses",
            "t_contacts",
            "Clients",
        })
    if "vulnerable" in q or "tag" in q:
        intent_tables.update({
            "t_jobs",
            "t_statuses",
            "t_contacts",
            "t_notifications",
            "Clients",
        })
    if "customer contact" in q or "contact" in q and ("customer" in q or "days" in q):
        intent_tables.update({
            "t_notifications",
            "t_jobs",
            "t_contacts",
            "t_statuses",
        })
    if "won" in q or "closed" in q or "lost" in q:
        intent_tables.update({
            "t_jobs",
            "t_statuses",
            "t_contacts",
            "Clients",
        })
    # "how many insurer clients", "insurer client group", "how many clients"
    if "how many" in q and ("client" in q or "insurer" in q):
        intent_tables.update({"Clients", "t_contacts", "t_jobs", "t_statuses"})
    # pivot / month-as-column queries always need Clients + t_jobs + t_statuses
    if "month" in q and ("column" in q or "heading" in q or "table" in q or "pivot" in q):
        intent_tables.update({"Clients", "t_contacts", "t_jobs", "t_statuses"})
    if "since" in q and ("2025" in q or "2026" in q or "january" in q):
        intent_tables.update({"t_jobs", "t_statuses", "t_contacts", "Clients"})
    if "notification" in q:
        intent_tables.update({
            "t_notifications",
            "t_jobs",
            "t_contacts",
        })
    if "allocation" in q:
        intent_tables.update({
            "t_allocations",
            "t_allocation-statuses",
            "t_contacts",
            "t_jobs",
        })
    if "reminder" in q:
        intent_tables.update({"t_reminders", "t_jobs", "t_users", "admin.QBCC-Policies"})
    if "work order" in q or "work-order" in q:
        intent_tables.update({
            "t_work-orders",
            "t_work-orders-items",
            "reporting.Work-Orders-Trades",
            "t_contacts",
            "t_statuses",
            "t_jobs",
            "t_allocations",
            "t_allocation-statuses",
        })

    if "invoice" in q or "xero" in q:
        intent_tables.update({
            # ENDATA invoice table (confirmed real name)
            "invoices",
            "t_serviceRequests",
            # PRIME AR/AP tables
            "t_accounts-receivable-invoices",
            "t_accounts-payable-invoices",
        })
    # ENDATA claim/service request queries
    if "endata" in q or "service request" in q:
        intent_tables.update({"t_serviceRequests", "s_serviceRequests", "invoices"})
    if "reporting" in q or "brand" in q:
        intent_tables.update({"reporting.Jobs", "t_statuses", "t_allocation-statuses", "Clients"})
    if "status" in q:
        intent_tables.update({"t_statuses", "t_allocation-statuses", "t_status-histories"})
    # --- IN4MO tables: all 7 tables link via ClaimsID ---
    _ALL_IN4MO_TABLES = {
        "In4mo.ClaimInformation", "In4mo.CostControl", "In4mo.WorkPlan",
        "In4mo.ProjectPlan", "In4mo.Invoice", "In4mo.Documents", "In4mo.ChatRoom",
    }
    # Any IN4MO-related keyword should include ALL IN4MO tables (only 7, safe to include all)
    # because cross-table queries are very common and all tables JOIN via ClaimsID.
    _in4mo_triggered = False
    if "claim" in q or "policy" in q or "premium" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        intent_tables.add("admin.QBCC-Policies")
        _in4mo_triggered = True
    if "inspection" in q or "property" in q or "damage" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "cost control" in q or ("cost" in q and "claim" in q):
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "work plan" in q or "workplan" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "project plan" in q or "schedule" in q or "task" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if ("invoice" in q or "submitted" in q) and ("claim" in q or "approved" in q or "lodg" in q):
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "document" in q or "attachment" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "chat" in q or "message" in q and "claim" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "lodg" in q or "loss" in q or "coverage" in q or "in4mo" in q:
        intent_tables.update(_ALL_IN4MO_TABLES)
        _in4mo_triggered = True
    if "qbcc" in q:
        intent_tables.update({"admin.QBCC-Policies", "t_jobs", "t_reminders", "t_estimates-snapshot", "t_job-expense-invoices"})
    if "construction" in q or "sow" in q or "authorised works" in q:
        intent_tables.update({
            "t_jobs", "t_statuses", "t_estimates-snapshot", "t_contacts",
            "Clients", "t_catastrophe-codes", "t_status-histories",
            "t_accounts-receivable-invoices",
        })
    if "active" in q and ("job" in q or "stage" in q):
        intent_tables.update({
            "t_jobs", "t_statuses", "t_contacts", "Clients",
        })
    if ("ar" in q or "accounts receivable" in q or "receivable" in q) and "invoice" in q:
        intent_tables.update({
            "t_accounts-receivable-invoices", "t_jobs", "t_users",
        })
    if ("ap" in q or "accounts payable" in q or "payable" in q) and "invoice" in q:
        intent_tables.update({
            "t_accounts-payable-invoices", "t_jobs", "t_work-orders",
        })
    if "open" in q and "allocation" in q:
        intent_tables.update({
            "t_allocations", "t_allocation-statuses", "t_jobs",
            "t_work-orders", "t_contacts",
        })
    if "finance" in q or "productivity" in q:
        intent_tables.update({
            "t_accounts-receivable-invoices", "t_accounts-payable-invoices", "t_users",
        })
    if "estimate" in q:
        intent_tables.update({"t_estimates", "t_estimate-items", "t_estimate-categories"})
    if "timesheet" in q or "roster" in q:
        intent_tables.update({"t_timesheets", "t_timesheet-activities", "t_roster", "t_contacts"})
    if "contract" in q and "band" in q:
        intent_tables.update({"model.contract", "t_jobs"})
    if "pending approval" in q and "band" in q:
        intent_tables.update({"model.pending", "t_jobs"})
    if "win rate" in q or "win rates" in q:
        intent_tables.update({"model.winrates", "model.precon_winrates", "t_jobs"})

    return intent_tables


def _compute_schema_limit(user_message: str, base_limit: int) -> int:
    tokens = _tokenize_message(user_message)
    if not tokens:
        return base_limit

    mention_terms = [
        "job",
        "allocation",
        "reminder",
        "work",
        "invoice",
        "claim",
        "policy",
        "inspection",
        "property",
        "brand",
    ]
    mention_count = sum(1 for term in mention_terms if term in tokens)
    if mention_count >= 3:
        # Multi-entity queries need MORE tables, not fewer — they require joins
        return min(40, int(base_limit * 1.3))
    if len(tokens) < 6:
        return min(35, int(base_limit * 1.5))
    return base_limit


def _expand_with_fk_neighbors(selected_tables: list[str], all_fks: list[dict], max_tables: int) -> list[str]:
    # Allow FK expansion to go beyond max_tables by a margin,
    # because missing a JOIN target table is worse than sending a few extra tables.
    fk_ceiling = max(max_tables + 6, int(max_tables * 1.5))

    selected_set = set(selected_tables)
    # Two-hop expansion: first expand direct neighbors, then neighbors-of-neighbors
    for _hop in range(2):
        if len(selected_set) >= fk_ceiling:
            break
        new_tables: set[str] = set()
        for fk in all_fks:
            parent = _table_key(fk["parent_schema"], fk["parent_table"])
            referenced = _table_key(fk["referenced_schema"], fk["referenced_table"])
            if parent in selected_set and referenced not in selected_set:
                new_tables.add(referenced)
            if referenced in selected_set and parent not in selected_set:
                new_tables.add(parent)
        selected_set.update(new_tables)
        if len(selected_set) >= fk_ceiling:
            break

    return list(selected_set)


def select_relevant_table_names(table_names: list[str], user_message: str, max_tables: int = 12) -> list[str]:
    if len(table_names) <= max_tables:
        return sorted(table_names)

    tokens = _tokenize_message(user_message)
    ranked = sorted(
        table_names,
        key=lambda table_name: (_score_table_name_only(table_name, tokens), table_name),
        reverse=True,
    )
    # Match intent tables flexibly: "In4mo.ClaimInformation" should match
    # "dbo.ClaimInformation" if the DB has it under a different schema.
    raw_intent = _intent_tables_from_message(user_message)
    intent_tables: list[str] = []
    table_name_index: dict[str, str] = {}
    for actual in table_names:
        short = actual.split(".", 1)[1].lower() if "." in actual else actual.lower()
        table_name_index[short] = actual
        table_name_index[actual.lower()] = actual

    for intent_t in raw_intent:
        low = intent_t.lower()
        if low in table_name_index:
            intent_tables.append(table_name_index[low])
        else:
            # Try matching by table name only (strip schema)
            short = intent_t.split(".", 1)[1].lower() if "." in intent_t else low
            if short in table_name_index:
                intent_tables.append(table_name_index[short])

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


def _synthetic_in4mo_fks(table_names: list[str]) -> list[dict]:
    """Generate synthetic FK relationships for IN4MO tables.

    All IN4MO tables link to ClaimInformation via ClaimsID, but these
    relationships may not exist as formal FK constraints in the database.
    Without them the LLM has no JOIN guidance for cross-table queries.
    """
    # Find the actual table keys in the selected schema (handles case variations)
    in4mo_tables: dict[str, str] = {}  # short_name -> actual_key
    for t in table_names:
        low = t.lower()
        if "in4mo." in low or "in4mo." in t:
            short = t.split(".", 1)[1] if "." in t else t
            in4mo_tables[short.lower()] = t

    claim_key = in4mo_tables.get("claiminformation")
    if not claim_key:
        return []

    claim_schema = claim_key.split(".", 1)[0] if "." in claim_key else "In4mo"

    # Tables that link to ClaimInformation via ClaimsID
    child_tables = ["costcontrol", "workplan", "projectplan", "invoice", "documents", "chatroom"]
    synthetic: list[dict] = []
    for child_short in child_tables:
        child_key = in4mo_tables.get(child_short)
        if not child_key:
            continue
        child_schema = child_key.split(".", 1)[0] if "." in child_key else "In4mo"
        child_table = child_key.split(".", 1)[1] if "." in child_key else child_key
        synthetic.append({
            "fk_name": f"synthetic_fk_{child_short}_claimsid",
            "parent_schema": child_schema,
            "parent_table": child_table,
            "parent_column": "ClaimsID",
            "referenced_schema": claim_schema,
            "referenced_table": claim_key.split(".", 1)[1] if "." in claim_key else claim_key,
            "referenced_column": "ClaimsID",
        })
    return synthetic


def load_schema_context(database_name: str | None, user_message: str, max_tables: int = 12) -> dict:
    chosen_db, _ = get_db_config_or_raise(database_name)
    candidate_table_names = fetch_table_names(chosen_db)
    adjusted_limit = _compute_schema_limit(user_message, max_tables)
    selected_tables = select_relevant_table_names(
        candidate_table_names,
        user_message=user_message,
        max_tables=adjusted_limit,
    )
    all_fks = fetch_foreign_keys(chosen_db)
    expanded_tables = _expand_with_fk_neighbors(selected_tables, all_fks, adjusted_limit)
    selected_schema = fetch_schema(chosen_db, table_filter=expanded_tables)
    selected_fk = fetch_foreign_keys(chosen_db, table_filter=set(expanded_tables))

    # Inject synthetic FK relationships for IN4MO tables (all JOIN via ClaimsID)
    synthetic_fks = _synthetic_in4mo_fks(expanded_tables)
    if synthetic_fks:
        selected_fk = selected_fk + synthetic_fks

    return {
        "database": chosen_db,
        "schema": selected_schema,
        "schema_text": format_schema_for_prompt(selected_schema),
        "foreign_keys": selected_fk,
        "fk_text": format_fk_for_prompt(selected_fk),
    }
