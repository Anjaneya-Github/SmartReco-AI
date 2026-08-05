"""Create the smartreco database if it does not exist."""
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5432, dbname="postgres",
    user="postgres", password="postgres123", connect_timeout=5,
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = 'smartreco'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE smartreco")
    print("Database 'smartreco' created.")
else:
    print("Database 'smartreco' already exists.")
conn.close()
