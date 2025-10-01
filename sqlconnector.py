import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

cnx = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3360")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", "toor"),
)
cnx.autocommit = True  # allow CREATE DATABASE outside a transaction

sql = (
    "CREATE DATABASE IF NOT EXISTS demo_app "
    "DEFAULT CHARACTER SET utf8mb4 "
    "COLLATE utf8mb4_0900_ai_ci"
)

with cnx.cursor() as cur:
    cur.execute(sql)

cnx.close()
print("Database demo_app ensured.")
