import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = os.getenv("MYSQL_PORT")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")

openai.api_key = OPENAI_API_KEY

# Database connection
def get_engine():
    url = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
    engine = create_engine(url)
    return engine

# Fetch schema from DB
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

# Generate SQL using OpenAI
def generate_sql(user_query, system_prompt):
    prompt = f"""
    You are a SQL assistant. The database schema is as follows:

    {system_prompt}

    User query: {user_query}
    
    Return only valid SQL query using the schema above. Use backticks for table/column names.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You generate SQL queries based on schema."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        sql = response['choices'][0]['message']['content'].strip()
        return sql
    except Exception as e:
        return f"-- Error generating SQL: {e}"

# Execute SQL
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
st.title("SQL Agent Streamlit App")

st.subheader("1️⃣ User Query Input (Natural Language)")
user_query = st.text_area("Enter your query in plain English", "")

st.subheader("2️⃣ System Prompt (Database Schema)")
if 'schema_text' not in st.session_state:
    st.session_state['schema_text'] = ""
if st.button("Auto-populate schema"):
    schema = fetch_schema()
    formatted_schema = "\n".join([f"{t}: {', '.join(cols)}" for t, cols in schema.items()])
    st.session_state['schema_text'] = formatted_schema

system_prompt = st.text_area("Database Schema / System Prompt", value=st.session_state['schema_text'], height=200)

st.subheader("3️⃣ Generated SQL Query")
if st.button("Generate SQL Query"):
    generated_sql = generate_sql(user_query, system_prompt)
    st.session_state['generated_sql'] = generated_sql

sql_query = st.text_area("Generated SQL (editable)", value=st.session_state.get('generated_sql', ""), height=150)

st.subheader("4️⃣ Execute SQL Query")
if st.button("Execute Query"):
    if sql_query.strip() == "":
        st.warning("SQL query is empty.")
    else:
        df = execute_query(sql_query)
        st.session_state['last_result'] = df

st.subheader("5️⃣ Query Results")
if 'last_result' in st.session_state:
    st.dataframe(st.session_state['last_result'])
