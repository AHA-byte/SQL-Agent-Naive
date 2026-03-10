# SQL Agent (Azure Function App + Streamlit Test Client)

This project is now structured for Azure deployment using a Python Azure Function App.
Streamlit remains available as a local test client and calls the same HTTP endpoints that Azure hosts.

## Architecture

- **Azure Function App**: server-side API for schema fetch, SQL generation, and SQL execution
- **Shared service layer** (`app/services.py`): DB + OpenAI logic used by Function endpoints
- **Streamlit app** (`sql_agent_openai_app.py`): local-only client UI that calls Function API

## API Endpoints

- `GET /api/health`
- `GET /api/databases`
- `POST /api/schema`
- `POST /api/generate-sql`
- `POST /api/execute`
- `POST /api/table-preview`

## Files Added for Azure Functions

- `function_app.py` (Azure Functions v2 programming model entry point)
- `host.json`
- `.funcignore`
- `local.settings.json.example`
- `app/config.py`
- `app/services.py`

## Security and Runtime Defaults

- SQL execution is restricted to read-only queries (`SELECT`/`WITH`)
- Dangerous SQL keywords are blocked (e.g. `DROP`, `ALTER`, `DELETE`)
- Table preview limit is capped
- SQL Server connection uses ODBC Driver 18 with encryption

## Local Development

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure environment

Create `.env` in project root:

```ini
# Function + Streamlit
FUNCTION_API_BASE_URL=http://localhost:7071/api
FUNCTION_API_KEY=

# OpenAI
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

# Azure SQL (Database 1)
AZURE_SQL_HOST=your-server.database.windows.net
AZURE_SQL_PORT=1433
AZURE_SQL_USER=your_user
AZURE_SQL_PASSWORD=your_password
AZURE_SQL_DB=your_database

# Azure SQL (Database 2)
AZURE_SQL_HOST_2=...
AZURE_SQL_USER_2=...
AZURE_SQL_PASSWORD_2=...
AZURE_SQL_DB_2=...

# Azure SQL (Database 3)
AZURE_SQL_HOST_3=...
AZURE_SQL_USER_3=...
AZURE_SQL_PASSWORD_3=...
AZURE_SQL_DB_3=...
```

### 3) Start Function App locally

Install Azure Functions Core Tools, then run:

```bash
func start
```

### 4) Start Streamlit test client

In a second terminal:

```bash
streamlit run sql_agent_openai_app.py
```

## Deploy to Azure Function App

### 1) Create Azure resources

- Resource group
- Storage account
- Function App (Python runtime)

### 2) Set app settings in Azure Function App

Set all required values from `.env` as Function App Application Settings:

- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `AZURE_SQL_*` values for each database profile

### 3) Deploy code

Use one of:

- VS Code Azure Functions extension deploy
- Azure CLI zip deploy
- CI/CD pipeline (GitHub Actions or Azure DevOps)

### 4) (Recommended) Harden for production

- Move secrets to Azure Key Vault
- Use Managed Identity where possible
- Restrict networking for Azure SQL
- Put APIM or auth in front of Function endpoints for Teams traffic

## Teams Integration (Next Step)

Teams bot/service should call these Function endpoints rather than connecting directly to DB or OpenAI.

## License

MIT
