import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import google.generativeai as genai  # Correct import

# Load environment variables
load_dotenv()

# API Key Configuration for Gemini API
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as e:
    st.error(f"Failed to configure Gemini API. Please check your GEMINI_API_KEY. Error: {e}")
    st.stop()

# Database connection function
def get_engine():
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = os.getenv("MYSQL_PORT")
    MYSQL_USER = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_DB = os.getenv("MYSQL_DB")
    
    url = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
    engine = create_engine(url)
    return engine

# Fetch database schema
def fetch_schema():
    engine = get_engine()
    with engine.connect() as conn:
        tables = conn.execute(text("SHOW TABLES")).fetchall()
        schema_dict = {}
        for t in tables:
            table_name = t[0]
            cols = conn.execute(text(f"SHOW COLUMNS FROM `{table_name}`")).fetchall()
            schema_dict[table_name] = [c[0] for c in cols]
        return schema_dict

# Fetch data from a specific table
def fetch_table_data(table_name, limit=20):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            query = f"SELECT * FROM `{table_name}` LIMIT {limit};"
            result = conn.execute(text(query))
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except Exception as e:
        return pd.DataFrame([["Error fetching data", str(e)]], columns=["Error", "Detail"])

# Generate SQL using Gemini API
def generate_sql(user_query, system_prompt):
    if not user_query or not system_prompt:
        return "-- Please provide a query and schema first."

    # This is the prompt template we'll send to the model
    prompt = f"""
    You are a world-class MySQL expert who translates natural language to SQL.
    Based on the following database schema, write a valid MySQL query to answer the user's request.

    Database Schema:
    ---
    {system_prompt}
    ---

    User Query: "{user_query}"

    SQL Query:
    """

    try:
        # Initialize the Gemini model for content generation
        model = genai.GenerativeModel('gemini-2.5-flash')  # Adjust model if needed
        # Generate content (SQL query)
        response = model.generate_content(prompt)
        # Clean up and return the generated SQL
        sql = response.text.strip().replace("```sql", "").replace("```", "").strip()
        return sql
    except Exception as e:
        return f"-- Error generating SQL: {e}"

# Execute SQL query against the database
def execute_query(sql):
    engine = get_engine()
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
st.title("SQL Agent Streamlit App with Gemini API")

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
                schema = fetch_schema()
                formatted_schema = "\n".join([f"{t}: {', '.join(cols)}" for t, cols in schema.items()])
                st.session_state['schema_text'] = formatted_schema

        system_prompt = st.text_area("Database Schema / System Prompt", value=st.session_state['schema_text'], height=200)

        # 3️⃣ Generate SQL Section
        st.subheader("3️⃣ Generated SQL Query")
        if st.button("Generate SQL Query"):
            with st.spinner("🤖 Gemini is thinking..."):
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
                    df = execute_query(sql_query)
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
    schema = fetch_schema()
    table_names = list(schema.keys())

    # Dropdown to select table
    table_name = st.selectbox("Select a table", table_names)

    # Show top 20 rows of the selected table
    if table_name:
        st.subheader(f"Top 20 rows from {table_name}")
        df_top = fetch_table_data(table_name, limit=20)
        st.dataframe(df_top)

        # Option to show all data
        if st.button("Show full table"):
            st.subheader(f"Full table: {table_name}")
            df_full = fetch_table_data(table_name, limit=1000)  # Show full table (limit to 1000 rows for performance)
            st.dataframe(df_full)
