"""Runtime configuration from environment variables."""
import os

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "my-test-project-279216")
DATASET = os.getenv("BIGQUERY_DATASET", "freight_analytics")
BQ_LOCATION = os.getenv("BIGQUERY_LOCATION", "US")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-pro")   # SQL reasoning and answers
FAST_MODEL = os.getenv("FAST_MODEL", "gemini-2.5-flash")    # document extraction, summaries

MAX_BYTES_PER_QUERY = int(os.getenv("MAX_BYTES_PER_QUERY", "200000000"))  # 200 MB per agent query
MAX_ROWS_RETURNED = 500
MAX_AGENT_STEPS = 8

# The agent may only query these curated views: no customer contact details, no raw tables.
ALLOWED_VIEWS = {"v_shipments", "v_terminals", "v_claims", "v_shipment_events", "v_bills_of_lading"}


def table(name: str) -> str:
    return f"`{PROJECT}.{DATASET}.{name}`"
