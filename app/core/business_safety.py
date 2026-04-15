"""
Business safety filter — blocklist approach.

Only blocks known system/internal tables and schemas.
All other tables pass through to the LLM.
"""

import re

# System schemas and table prefixes that should NEVER be exposed to the LLM.
BLOCKED_PREFIXES = {
    "sys.",
    "information_schema.",
    "sys_",
    "msdb.",
    "tempdb.",
    "master.",
}

BLOCKED_EXACT = {
    "sys",
    "information_schema",
    "sysdiagrams",
    "dtproperties",
    "__efmigrationshistory",
    "__migrationhistory",
}

BLOCKED_TOKENS = {
    "suser",
    "session",
    "original_login",
    "spid",
    "host_name",
}


def _normalize(identifier: str) -> str:
    return (identifier or "").lower().strip()


def is_system_or_internal_identifier(identifier: str) -> bool:
    """Return True if the identifier looks like a system/internal object."""
    lowered = _normalize(identifier)
    if not lowered:
        return False

    if lowered in BLOCKED_EXACT:
        return True

    if any(lowered.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return True

    tokens = set(re.findall(r"[a-zA-Z0-9_]+", lowered))
    return bool(tokens & BLOCKED_TOKENS)


def is_business_table_for_db(database_name: str | None, table_key: str) -> bool:
    """Return True unless the table is a known system/internal object."""
    return not is_system_or_internal_identifier(table_key)


def filter_business_table_candidates(
    database_name: str | None, table_keys: list[str]
) -> list[str]:
    """Filter out system tables. All business tables pass through."""
    return [t for t in table_keys if not is_system_or_internal_identifier(t)]
