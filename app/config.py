import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: str
    user: str
    password: str
    db: str


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
            os.getenv("AZURE_SQL_PASSWORD"),
            os.getenv("AZURE_SQL_DB"),
        ),
        "PRIME": _database_entry(
            os.getenv("AZURE_SQL_HOST_2"),
            os.getenv("AZURE_SQL_PORT", "1433"),
            os.getenv("AZURE_SQL_USER_2"),
            os.getenv("AZURE_SQL_PASSWORD_2"),
            os.getenv("AZURE_SQL_DB_2"),
        ),
        "ENDATA": _database_entry(
            os.getenv("AZURE_SQL_HOST_3"),
            os.getenv("AZURE_SQL_PORT", "1433"),
            os.getenv("AZURE_SQL_USER_3"),
            os.getenv("AZURE_SQL_PASSWORD_3"),
            os.getenv("AZURE_SQL_DB_3"),
        ),
    }

    return {name: cfg for name, cfg in candidates.items() if cfg is not None}


def get_openai_settings() -> tuple[str | None, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return api_key, model
