import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()  # reads .env in the same folder

HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
PORT = os.getenv("MYSQL_PORT", "3360")  # your instance
USER = os.getenv("MYSQL_USER", "root")
PWD  = os.getenv("MYSQL_PASSWORD", "toor")

# connect without selecting a DB
engine = create_engine(f"mysql+mysqlconnector://{USER}:{PWD}@{HOST}:{PORT}")

sql = """
CREATE DATABASE IF NOT EXISTS demo_app
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
"""

with engine.begin() as conn:
    conn.execute(text(sql))

print("Database demo_app ensured.")
