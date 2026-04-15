import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

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
    user: str | None
    password: str | None
    db: str
    auth_mode: str | None = None
    msi_client_id: str | None = None


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


def _database_entry(
    host: str | None,
    port: str | None,
    user: str | None,
    password: str | None,
    db: str | None,
    auth_mode: str | None = None,
    msi_client_id: str | None = None,
) -> DatabaseConfig | None:
    if not host or not db:
        return None

    using_msi = bool(auth_mode and "activedirectory" in auth_mode.lower())
    if not using_msi and (not user or not password):
        return None

    return DatabaseConfig(
        host=host,
        port=port or "1433",
        user=user,
        password=password,
        db=db,
        auth_mode=auth_mode,
        msi_client_id=msi_client_id,
    )


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def _clean_secret(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
        return text[1:-1]
    return text


def get_available_databases() -> dict[str, DatabaseConfig]:
    candidates = {
        "IN4MO": _database_entry(
            _first_env("AZURE_SQL_HOST", "DB_IN4MO_SERVER"),
            _first_env("AZURE_SQL_PORT", "DB_IN4MO_PORT", "DB_SQL_PORT", "1433"),
            _first_env("AZURE_SQL_USER", "DB_IN4MO_USER", "DB_SQL_USER"),
            _clean_secret(
                _first_env("AZURE_SQL_PASSWORD", "DB_IN4MO_PASSWORD", "DB_SQL_PASSWORD")
                or _resolve_secret("AZURE_SQL_PASSWORD", "AZURE_SQL_PASSWORD_SECRET_NAME")
            ),
            _first_env("AZURE_SQL_DB", "DB_IN4MO_DATABASE"),
            _first_env("AZURE_SQL_AUTH_MODE", "DB_SQL_AUTH_MODE", "DB_IN4MO_AUTH_MODE"),
            _first_env("AZURE_CLIENT_ID", "DB_SQL_MSI_CLIENT_ID", "AzureWebJobsStorage__clientId"),
        ),
        "PRIME": _database_entry(
            _first_env("AZURE_SQL_HOST_2", "DB_PRIME_SERVER"),
            _first_env("AZURE_SQL_PORT", "DB_PRIME_PORT", "DB_SQL_PORT", "1433"),
            _first_env("AZURE_SQL_USER_2", "DB_PRIME_USER", "DB_SQL_USER"),
            _clean_secret(
                _first_env("AZURE_SQL_PASSWORD_2", "DB_PRIME_PASSWORD", "DB_SQL_PASSWORD")
                or _resolve_secret("AZURE_SQL_PASSWORD_2", "AZURE_SQL_PASSWORD_SECRET_NAME_2")
            ),
            _first_env("AZURE_SQL_DB_2", "DB_PRIME_DATABASE"),
            _first_env("AZURE_SQL_AUTH_MODE", "DB_SQL_AUTH_MODE", "DB_PRIME_AUTH_MODE"),
            _first_env("AZURE_CLIENT_ID", "DB_SQL_MSI_CLIENT_ID", "AzureWebJobsStorage__clientId"),
        ),
        "ENDATA": _database_entry(
            _first_env("AZURE_SQL_HOST_3", "DB_ENDATA_SERVER"),
            _first_env("AZURE_SQL_PORT", "DB_ENDATA_PORT", "DB_SQL_PORT", "1433"),
            _first_env("AZURE_SQL_USER_3", "DB_ENDATA_USER", "DB_SQL_USER"),
            _clean_secret(
                _first_env("AZURE_SQL_PASSWORD_3", "DB_ENDATA_PASSWORD", "DB_SQL_PASSWORD")
                or _resolve_secret("AZURE_SQL_PASSWORD_3", "AZURE_SQL_PASSWORD_SECRET_NAME_3")
            ),
            _first_env("AZURE_SQL_DB_3", "DB_ENDATA_DATABASE"),
            _first_env("AZURE_SQL_AUTH_MODE", "DB_SQL_AUTH_MODE", "DB_ENDATA_AUTH_MODE"),
            _first_env("AZURE_CLIENT_ID", "DB_SQL_MSI_CLIENT_ID", "AzureWebJobsStorage__clientId"),
        ),
    }

    return {name: cfg for name, cfg in candidates.items() if cfg is not None}


def get_openai_settings() -> tuple[str | None, str]:
    api_key = _resolve_secret("OPENAI_API_KEY", "OPENAI_API_KEY_SECRET_NAME") or _first_env(
        "AZURE_OPENAI_KEY"
    )
    model = _first_env("OPENAI_MODEL", "CHAT_MODEL_DEPLOYMENT_NAME", "AZURE_OPENAI_MODEL") or "gpt-4o-mini"
    return api_key, model


def get_azure_openai_endpoint() -> str | None:
    return _first_env("AZURE_OPENAI_ENDPOINT", "AzureOpenAI__endpoint")


def get_default_database_name(dbs: dict[str, DatabaseConfig] | None = None) -> str | None:
    databases = dbs or get_available_databases()
    configured = os.getenv("DEFAULT_DATABASE", "").strip().upper()
    if configured and configured in databases:
        return configured
    return sorted(databases.keys())[0] if databases else None


def get_allowed_schemas() -> set[str]:
    raw = os.getenv("ALLOWED_SQL_SCHEMAS", "dbo,admin,model,reporting,xero,in4mo,overflow")
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def get_schema_table_limit() -> int:
    try:
        value = int(os.getenv("SCHEMA_TABLE_LIMIT", "30"))
        return max(1, min(value, 120))
    except ValueError:
        return 30


def get_schema_cache_ttl() -> int:
    try:
        value = int(os.getenv("SCHEMA_CACHE_TTL", "300"))
        return max(30, min(value, 3600))
    except ValueError:
        return 300
