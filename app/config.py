import os
from dataclasses import dataclass

from dotenv import load_dotenv

try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
except ImportError:
    DefaultAzureCredential = None
    SecretClient = None

load_dotenv()

_SECRET_CACHE: dict[str, str] = {}
_KEY_VAULT_CLIENT = None


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: str
    user: str
    password: str
    db: str


def _get_key_vault_client():
    global _KEY_VAULT_CLIENT

    key_vault_url = os.getenv("KEY_VAULT_URL", "").strip()
    if not key_vault_url or not DefaultAzureCredential or not SecretClient:
        return None

    if _KEY_VAULT_CLIENT is None:
        credential = DefaultAzureCredential()
        _KEY_VAULT_CLIENT = SecretClient(vault_url=key_vault_url, credential=credential)

    return _KEY_VAULT_CLIENT


def _resolve_secret(value_env_key: str, secret_name_env_key: str) -> str | None:
    if raw_value := os.getenv(value_env_key):
        return raw_value

    secret_name = os.getenv(secret_name_env_key)
    if not secret_name:
        return None

    if secret_name in _SECRET_CACHE:
        return _SECRET_CACHE[secret_name]

    client = _get_key_vault_client()
    if not client:
        return None

    secret_value = client.get_secret(secret_name).value
    _SECRET_CACHE[secret_name] = secret_value
    return secret_value


def _database_entry(host: str | None, port: str | None, user: str | None, password: str | None, db: str | None) -> DatabaseConfig | None:
    if not host or not user or not db:
        return None
    return DatabaseConfig(
        host=host,
        port=port or "1433",
        user=user,
        password=password or "",
        db=db,
    )


def get_available_databases() -> dict[str, DatabaseConfig]:
    candidates = {
        "IN4MO": _database_entry(
            os.getenv("AZURE_SQL_HOST"),
            os.getenv("AZURE_SQL_PORT", "1433"),
            os.getenv("AZURE_SQL_USER"),
            _resolve_secret("AZURE_SQL_PASSWORD", "AZURE_SQL_PASSWORD_SECRET_NAME"),
            os.getenv("AZURE_SQL_DB"),
        ),
        "PRIME": _database_entry(
            os.getenv("AZURE_SQL_HOST_2"),
            os.getenv("AZURE_SQL_PORT", "1433"),
            os.getenv("AZURE_SQL_USER_2"),
            _resolve_secret("AZURE_SQL_PASSWORD_2", "AZURE_SQL_PASSWORD_SECRET_NAME_2"),
            os.getenv("AZURE_SQL_DB_2"),
        ),
        "ENDATA": _database_entry(
            os.getenv("AZURE_SQL_HOST_3"),
            os.getenv("AZURE_SQL_PORT", "1433"),
            os.getenv("AZURE_SQL_USER_3"),
            _resolve_secret("AZURE_SQL_PASSWORD_3", "AZURE_SQL_PASSWORD_SECRET_NAME_3"),
            os.getenv("AZURE_SQL_DB_3"),
        ),
    }

    return {name: cfg for name, cfg in candidates.items() if cfg is not None}


def get_openai_settings() -> tuple[str | None, str]:
    api_key = _resolve_secret("OPENAI_API_KEY", "OPENAI_API_KEY_SECRET_NAME")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return api_key, model


def get_default_database_name(dbs: dict[str, DatabaseConfig] | None = None) -> str | None:
    databases = dbs or get_available_databases()
    configured = os.getenv("DEFAULT_DATABASE", "").strip()
    if configured and configured in databases:
        return configured
    return sorted(databases.keys())[0] if databases else None


def get_allowed_schemas() -> set[str]:
    raw = os.getenv("ALLOWED_SQL_SCHEMAS", "dbo")
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def get_schema_table_limit() -> int:
    try:
        value = int(os.getenv("SCHEMA_TABLE_LIMIT", "12"))
        return max(1, min(value, 50))
    except ValueError:
        return 12
