import psycopg2
from psycopg2.extras import Json

db_url = f"postgresql://postgres:postgres@localhost:5432/incident_details"

pg_conn = psycopg2.connect(db_url)
pg_conn.autocommit = True

query = """
CREATE TABLE IF NOT EXISTS incident_details(
    id SERIAL PRIMARY KEY,
    incident_id VARCHAR(50) UNIQUE,
    type TEXT,
    description TEXT,
    severity TEXT,
    remediation TEXT,
    slack_channel TEXT,
    jira_ticket_url TEXT,
    kb_matches JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

with pg_conn.cursor() as cur:
    cur.execute(query)
    print("Table 'incident_details' succesfully created")
