import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from urllib.parse import quote_plus
from openai import OpenAI

# Load environment variables
load_dotenv()

# API Key Configuration for OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY not found in environment variables")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

# Database configurations - Support multiple Azure SQL databases
DATABASES = {
    "IN4MO": {
        "host": os.getenv("AZURE_SQL_HOST"),
        "port": os.getenv("AZURE_SQL_PORT", "1433"),
        "user": os.getenv("AZURE_SQL_USER"),
        "password": quote_plus(os.getenv("AZURE_SQL_PASSWORD", "")),
        "db": os.getenv("AZURE_SQL_DB"),
    },
    "PRIME": {
        "host": os.getenv("AZURE_SQL_HOST_2"),
        "port": os.getenv("AZURE_SQL_PORT", "1433"),
        "user": os.getenv("AZURE_SQL_USER_2"),
        "password": quote_plus(os.getenv("AZURE_SQL_PASSWORD_2", "")),
        "db": os.getenv("AZURE_SQL_DB_2"),
    },
    "ENDATA": {
        "host": os.getenv("AZURE_SQL_HOST_3"),
        "port": os.getenv("AZURE_SQL_PORT", "1433"),
        "user": os.getenv("AZURE_SQL_USER_3"),
        "password": quote_plus(os.getenv("AZURE_SQL_PASSWORD_3", "")),
        "db": os.getenv("AZURE_SQL_DB_3"),
    }
}

# Filter out databases with missing credentials
AVAILABLE_DATABASES = {k: v for k, v in DATABASES.items() if v["host"] and v["user"] and v["db"]}

# Database connection function - supports selected database
def get_engine(db_config=None):
    if db_config is None:
        db_config = list(AVAILABLE_DATABASES.values())[0]  # Use first available
    
    url = f"mssql+pyodbc://{db_config['user']}:{db_config['password']}@{db_config['host']}:1433/{db_config['db']}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    engine = create_engine(url)
    return engine

# Fetch database schema
def fetch_schema(db_config=None):
    engine = get_engine(db_config)
    with engine.connect() as conn:
        query = text("""
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
        """)
        tables = conn.execute(query).fetchall()
        schema_dict = {}
        for t in tables:
            table_name = t[0]
            col_query = text(f"""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = '{table_name}'
            """)
            cols = conn.execute(col_query).fetchall()
            schema_dict[table_name] = [c[0] for c in cols]
        return schema_dict

# Fetch data from a specific table
def fetch_table_data(table_name, limit=20, db_config=None):
    engine = get_engine(db_config)
    try:
        with engine.connect() as conn:
            query = f"SELECT TOP {limit} * FROM [{table_name}];"
            result = conn.execute(text(query))
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except Exception as e:
        return pd.DataFrame([["Error fetching data", str(e)]], columns=["Error", "Detail"])

# Generate SQL using OpenAI
def generate_sql(user_query, system_prompt):
    if not user_query or not system_prompt:
        return "-- Please provide a query and schema first."

    prompt = f"""
    You are a world-class T-SQL (SQL Server) expert who translates natural language to SQL.
    Based on the following database schema, write a valid T-SQL query to answer the user's request.

    Database Schema:
    ---
    {system_prompt}
    ---

    User Query: "{user_query}"

    IMPORTANT RULES:
    - Use square brackets [table_name] and [column_name] for identifiers
    - Use TOP n instead of LIMIT n
    - Return only the SQL query, no markdown formatting

    T-SQL Query:
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert T-SQL/SQL Server query generator. Always use square brackets for identifiers and TOP for limiting rows. Return only raw SQL without markdown."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        sql = response.choices[0].message.content.strip()
        # Remove markdown code blocks if present
        sql = sql.replace("```sql\n", "").replace("```", "").strip()
        return sql
    except Exception as e:
        return f"-- Error generating SQL: {e}"

# Execute SQL query against the database
def execute_query(sql, db_config=None):
    engine = get_engine(db_config)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except Exception as e:
        return pd.DataFrame([["Error executing query", str(e)]], columns=["Error", "Detail"])

# --- Streamlit UI ---

# Set page configuration
st.set_page_config(layout="wide")

# Title of the app
st.title("SQL Agent Streamlit App with OpenAI API")

# Database selector at the top
st.subheader("📊 Select Database")
selected_db = st.selectbox("Choose a database:", list(AVAILABLE_DATABASES.keys()))
current_db_config = AVAILABLE_DATABASES[selected_db]

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
                schema = fetch_schema(current_db_config)
                formatted_schema = "\n".join([f"{t}: {', '.join(cols)}" for t, cols in schema.items()])
                st.session_state['schema_text'] = formatted_schema

        system_prompt = st.text_area("Database Schema / System Prompt", value=st.session_state['schema_text'], height=200)

        # 3️⃣ Generate SQL Section
        st.subheader("3️⃣ Generated SQL Query")
        if st.button("Generate SQL Query"):
            with st.spinner("OpenAI is thinking..."):
                generated_sql = generate_sql(user_query, system_prompt)
                st.session_state['generated_sql'] = generated_sql

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
                    df = execute_query(sql_query, current_db_config)
                    st.session_state['last_result'] = df

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
    
    # Fetch the table names from the schema
    schema = fetch_schema(current_db_config)
    table_names = list(schema.keys())

    # Dropdown to select table
    table_name = st.selectbox("Select a table", table_names)

    # Show top 20 rows of the selected table
    if table_name:
        st.subheader(f"Top 20 rows from {table_name}")
        df_top = fetch_table_data(table_name, limit=20, db_config=current_db_config)
        st.dataframe(df_top)

        # Option to show all data
        if st.button("Show full table"):
            st.subheader(f"Full table: {table_name}")
            df_full = fetch_table_data(table_name, limit=1000, db_config=current_db_config)  # Show full table (limit to 1000 rows for performance)
            st.dataframe(df_full)
