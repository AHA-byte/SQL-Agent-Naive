import os

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

FUNCTION_API_BASE_URL = os.getenv("FUNCTION_API_BASE_URL", "http://localhost:7071/api").rstrip("/")
FUNCTION_API_KEY = os.getenv("FUNCTION_API_KEY", "")


def _api_url(path: str) -> str:
    return f"{FUNCTION_API_BASE_URL}/{path.lstrip('/')}"


def _api_post(path: str, payload: dict) -> dict:
    params = {"code": FUNCTION_API_KEY} if FUNCTION_API_KEY else None
    resp = requests.post(_api_url(path), json=payload, params=params, timeout=120)
    if not resp.ok:
        try:
            body = resp.json()
            error_message = body.get("error", f"HTTP {resp.status_code}")
        except Exception:
            error_message = f"HTTP {resp.status_code}"
        raise RuntimeError(error_message)
    return resp.json()


def _api_get(path: str) -> dict:
    params = {"code": FUNCTION_API_KEY} if FUNCTION_API_KEY else None
    resp = requests.get(_api_url(path), params=params, timeout=60)
    if not resp.ok:
        try:
            body = resp.json()
            error_message = body.get("error", f"HTTP {resp.status_code}")
        except Exception:
            error_message = f"HTTP {resp.status_code}"
        raise RuntimeError(error_message)
    return resp.json()

# --- Streamlit UI ---

# Set page configuration
st.set_page_config(layout="wide")

# Title of the app
st.title("SQL Agent Streamlit App with OpenAI API")

# Database selector at the top
st.subheader("📊 Select Database")
try:
    db_response = _api_get("databases")
    available_databases = db_response.get("databases", [])
except Exception as exc:
    st.error(f"Failed to connect to Function API: {exc}")
    st.info("Set FUNCTION_API_BASE_URL in .env. Example: http://localhost:7071/api")
    st.stop()

if not available_databases:
    st.error("No databases available from backend configuration.")
    st.stop()

selected_db = st.selectbox("Choose a database:", available_databases)

# Initialize session state variables
if 'schema_text' not in st.session_state:
    st.session_state['schema_text'] = ""
if 'generated_sql' not in st.session_state:
    st.session_state['generated_sql'] = ""
if 'last_result' not in st.session_state:
    st.session_state['last_result'] = pd.DataFrame()

# Tab Layout
tab1, tab2 = st.tabs(["SQL Query", "Database Tables"])

# --- SQL Query Tab ---
with tab1:
    # Create a container for centered layout
    with st.container():
        # 1️⃣ User Query Input Section
        st.subheader("1️⃣ User Query Input (Natural Language)")
        user_query = st.text_area("Enter your query in plain English:", height=100)

        # 2️⃣ System Prompt Section (Schema)
        st.subheader("2️⃣ System Prompt (Database Schema)")
        if st.button("Auto-populate schema"):
            with st.spinner("Fetching schema..."):
                try:
                    response = _api_post("schema", {"database": selected_db})
                    st.session_state['schema_text'] = response.get("schema_text", "")
                except Exception as exc:
                    st.error(f"Schema fetch failed: {exc}")

        system_prompt = st.text_area("Database Schema / System Prompt", value=st.session_state['schema_text'], height=200)

        # 3️⃣ Generate SQL Section
        st.subheader("3️⃣ Generated SQL Query")
        if st.button("Generate SQL Query"):
            with st.spinner("OpenAI is thinking..."):
                try:
                    response = _api_post(
                        "generate-sql",
                        {
                            "user_query": user_query,
                            "schema_text": system_prompt,
                        },
                    )
                    st.session_state['generated_sql'] = response.get("sql", "")
                except Exception as exc:
                    st.error(f"SQL generation failed: {exc}")

        # 4️⃣ SQL Query Display Section
        st.subheader("4️⃣ SQL Query (editable)")
        sql_query = st.text_area("Generated SQL (editable)", value=st.session_state.get('generated_sql', ""), height=200)

        # 5️⃣ Execute Query Section
        st.subheader("5️⃣ Execute SQL Query")
        if st.button("Execute SQL Query"):
            if sql_query.strip() == "":
                st.warning("SQL query is empty.")
            else:
                with st.spinner("Executing query..."):
                    try:
                        response = _api_post(
                            "execute",
                            {
                                "database": selected_db,
                                "sql": sql_query,
                                "max_rows": 1000,
                            },
                        )
                        st.session_state['last_result'] = pd.DataFrame(response.get("rows", []))
                    except Exception as exc:
                        st.error(f"Query execution failed: {exc}")

    # Divider between UI sections
    st.divider()

    # 6️⃣ Query Results Section
    st.subheader("6️⃣ Query Results")
    if 'last_result' in st.session_state and not st.session_state['last_result'].empty:
        st.dataframe(st.session_state['last_result'])
    else:
        st.info("Results will appear here after executing a query.")

# --- Database Tables Tab ---
with tab2:
    st.subheader("Database Tables")

    table_names = []
    try:
        response = _api_post("schema", {"database": selected_db})
        table_names = list(response.get("schema", {}).keys())
    except Exception as exc:
        st.error(f"Failed to load tables: {exc}")

    # Dropdown to select table
    table_name = st.selectbox("Select a table", table_names) if table_names else None

    # Show top 20 rows of the selected table
    if table_name:
        st.subheader(f"Top 20 rows from {table_name}")
        try:
            top_resp = _api_post(
                "table-preview",
                {"database": selected_db, "table": table_name, "limit": 20},
            )
            df_top = pd.DataFrame(top_resp.get("rows", []))
            st.dataframe(df_top)
        except Exception as exc:
            st.error(f"Failed to fetch table preview: {exc}")

        # Option to show all data
        if st.button("Show full table"):
            st.subheader(f"Full table: {table_name}")
            try:
                full_resp = _api_post(
                    "table-preview",
                    {"database": selected_db, "table": table_name, "limit": 1000},
                )
                df_full = pd.DataFrame(full_resp.get("rows", []))
                st.dataframe(df_full)
            except Exception as exc:
                st.error(f"Failed to fetch full table: {exc}")
