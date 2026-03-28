# SQL Agent Backend (Azure Function App)

This project is a backend-first SQL agent hosted on Azure Functions.
It receives a message, loads bounded schema context, generates SQL, validates SQL safety, executes a read-only query, and returns structured JSON.

## Architecture

- **Azure Function App**: HTTP API entrypoints
- **Message API** (`POST /api/messages`): normalized simple/Bot payloads
- **Core modules** (`app/core/*`): schema loading, prompt building, SQL generation, validation, execution, formatting, bot response adaptation

## API Endpoints

- `GET /api/health`
- `GET /api/databases`
- `POST /api/schema`
- `POST /api/generate-sql`
- `POST /api/execute`
- `POST /api/table-preview`
- `POST /api/messages` (primary Phase 1 endpoint)

## Key Backend Files

- `function_app.py`
- `app/api/messages.py`
- `app/main.py`
- `app/core/schema_loader.py`
- `app/core/prompt_builder.py`
- `app/core/sql_generator.py`
- `app/core/sql_validator.py`
- `app/core/db_executor.py`
- `app/core/response_formatter.py`
- `app/core/response_adapter.py`

## Security and Runtime Defaults

- SQL execution is restricted to read-only queries (`SELECT`/`WITH`)
- Validator blocks multi-statement SQL, comments, DML/DDL/EXEC, `xp_`/`sp_`, `sys.` access
- Allowed schemas are enforced (`dbo` by default, configurable)
- Schema context is bounded to a relevant top-N table subset to avoid oversized prompts
- Row limits are enforced on execution
- SQL Server connection uses ODBC Driver 18 with encryption

## Local Development

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure environment

Create `.env` in project root:

```ini
# Function
FUNCTION_API_KEY=

# OpenAI
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_KEY_SECRET_NAME=optional-key-vault-secret-name

# Azure SQL (Database 1)
AZURE_SQL_HOST=your-server.database.windows.net
AZURE_SQL_PORT=1433
AZURE_SQL_USER=your_user
AZURE_SQL_PASSWORD=your_password
AZURE_SQL_PASSWORD_SECRET_NAME=optional-key-vault-secret-name
AZURE_SQL_DB=your_database

# Azure SQL (Database 2)
AZURE_SQL_HOST_2=...
AZURE_SQL_USER_2=...
AZURE_SQL_PASSWORD_2=...
AZURE_SQL_PASSWORD_SECRET_NAME_2=...
AZURE_SQL_DB_2=...

# Azure SQL (Database 3)
AZURE_SQL_HOST_3=...
AZURE_SQL_USER_3=...
AZURE_SQL_PASSWORD_3=...
AZURE_SQL_PASSWORD_SECRET_NAME_3=...
AZURE_SQL_DB_3=...

# Optional defaults
DEFAULT_DATABASE=IN4MO
ALLOWED_SQL_SCHEMAS=dbo
SCHEMA_TABLE_LIMIT=12

# Optional Key Vault
KEY_VAULT_URL=https://your-vault-name.vault.azure.net/
```

### 3) Start Function App locally

Install Azure Functions Core Tools, then run:

```bash
func start
```

### 4) Test the message endpoint locally

Simple payload:

```bash
curl -X POST http://localhost:7071/api/messages \
	-H "Content-Type: application/json" \
	-d "{\"message\":\"show top 10 customers by sales\",\"database\":\"IN4MO\",\"conversation_id\":\"abc123\",\"user_id\":\"user1\"}"
```

Bot Framework payload:

```bash
curl -X POST http://localhost:7071/api/messages \
	-H "Content-Type: application/json" \
	-d "{\"type\":\"message\",\"text\":\"show top 10 customers by sales\",\"conversation\":{\"id\":\"abc123\"},\"from\":{\"id\":\"user1\"},\"channelData\":{\"database\":\"IN4MO\"}}"
```

## Deploy to Azure Function App

### 1) Create Azure resources

- Resource group
- Storage account
- Function App (Python runtime)

### 2) Set app settings in Azure Function App

Set all required values from `.env` as Function App Application Settings:

- `OPENAI_API_KEY` or `OPENAI_API_KEY_SECRET_NAME`
- `AZURE_SQL_*` values for each database profile and optional `*_SECRET_NAME` values
- `KEY_VAULT_URL` if using managed identity + Key Vault

### 3) Deploy code

Use one of:

- VS Code Azure Functions extension deploy
- Azure CLI zip deploy
- CI/CD pipeline (GitHub Actions or Azure DevOps)

### 4) (Recommended) Harden for production

- Move secrets to Azure Key Vault
- Use managed identity for secret retrieval
- Restrict networking for Azure SQL
- Put APIM or auth in front of Function endpoints for Teams traffic

## Teams Integration (Next Step)

Teams bot/service should call `POST /api/messages` and receive Bot Framework-compatible responses.

## License

MIT
