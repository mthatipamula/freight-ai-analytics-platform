"""Governance for AI-generated SQL. Every query the agent writes passes these checks before it runs:

1. One read-only statement: no DML/DDL/scripting keywords, no multiple statements.
2. Approved data only: every table referenced must be one of the curated views (no raw tables, no customer
   contact details, no INFORMATION_SCHEMA). CTE names defined in the query itself are allowed.
3. BigQuery dry run: must be a SELECT, and must scan no more than MAX_BYTES_PER_QUERY.
4. Execution with maximum_bytes_billed (BigQuery enforces the cost cap too) and a row limit.
5. Every attempt, allowed or blocked, is written to the audit log.

In production the agent's service account would additionally have IAM access only to an "authorized views"
dataset, so the database itself refuses anything else. These checks are defense in depth on top of IAM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import bigquery

from . import config

log = logging.getLogger(__name__)

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|EXPORT|LOAD|CALL|EXECUTE|DECLARE|SET|BEGIN)\b",
    re.IGNORECASE)
TOKEN = re.compile(r"`[^`]+`|[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*|\(|\)|,|\S")
CTE_NAME = re.compile(r"(?:\bWITH\b|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE)
# Words that end a FROM list, so they are never mistaken for a table alias.
CLAUSE_WORDS = {"WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "LEFT", "RIGHT", "INNER", "FULL", "CROSS", "ON", "USING",
                "HAVING", "QUALIFY", "WINDOW", "UNION", "EXCEPT", "INTERSECT", "TABLESAMPLE", "FOR"}


class QueryBlocked(Exception):
    pass


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list]
    bytes_processed: int
    truncated: bool


def _strip_comments_and_strings(sql: str) -> str:
    sql = re.sub(r"--[^\n]*|#[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", sql)


def _table_refs(body: str) -> list[str]:
    """Every table named in a FROM or JOIN position, including comma-separated lists ("FROM a, b").
    Subqueries are walked too; the FROM inside EXTRACT(... FROM col) and table functions like UNNEST(...) are skipped."""
    toks = TOKEN.findall(body)
    refs: list[str] = []
    openers: list[str] = []  # the word before each open parenthesis
    for i, t in enumerate(toks):
        if t == "(":
            openers.append(toks[i - 1].upper() if i else "")
        elif t == ")":
            if openers:
                openers.pop()
        elif t.upper() in ("FROM", "JOIN") and not (openers and openers[-1] == "EXTRACT"):
            j = i + 1
            while j < len(toks) and toks[j] != "(" and not (j + 1 < len(toks) and toks[j + 1] == "("):
                refs.append(toks[j])
                k = j + 1
                if k < len(toks) and toks[k].upper() == "AS":
                    k += 1
                if k < len(toks) and re.match(r"[A-Za-z_`]", toks[k]) and toks[k].upper() not in CLAUSE_WORDS:
                    k += 1  # alias
                if k < len(toks) and toks[k] == ",":
                    j = k + 1
                    continue
                break
    return refs


def error_text(err: Exception) -> str:
    """BigQuery's error message without the request URL and job id around it."""
    msg = re.sub(r"^(\d{3} )?(POST|GET) \S+: ", "", getattr(err, "message", None) or str(err))
    return re.sub(r"\s*Location: .*$", "", msg, flags=re.DOTALL)


def check_sql(sql: str) -> None:
    """Static checks. Raises QueryBlocked with a reason the model can act on."""
    body = _strip_comments_and_strings(sql).strip().rstrip(";")
    if ";" in body:
        raise QueryBlocked("Only one SQL statement is allowed.")
    if not re.match(r"^\s*(SELECT|WITH)\b", body, re.IGNORECASE):
        raise QueryBlocked("Only SELECT queries are allowed.")
    if m := FORBIDDEN.search(body):
        raise QueryBlocked(f"'{m.group(1).upper()}' is not allowed: queries are read-only.")
    if "INFORMATION_SCHEMA" in body.upper():
        raise QueryBlocked("Metadata tables are not available; the approved views and their columns are listed in your instructions.")
    ctes = {n.lower() for n in CTE_NAME.findall(body)}
    for ref in _table_refs(body):
        name = ref.strip("`")
        parts = name.split(".")
        short = parts[-1].lower()
        if len(parts) == 1 and short in ctes:
            continue
        if len(parts) >= 2 and parts[-2] != config.DATASET:
            raise QueryBlocked(f"Table {name} is outside the approved dataset.")
        if len(parts) == 3 and parts[0] != config.PROJECT:
            raise QueryBlocked(f"Table {name} is outside the approved project.")
        if short not in config.ALLOWED_VIEWS:
            raise QueryBlocked(
                f"Table '{short}' is not approved for AI queries. Use only: {', '.join(sorted(config.ALLOWED_VIEWS))}. "
                "Customer contact details are not available.")


_client: bigquery.Client | None = None


def client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.PROJECT, location=config.BQ_LOCATION)
    return _client


def run_query(sql: str, session_id: str, question: str) -> QueryResult:
    try:
        check_sql(sql)
        job_config = bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False,
            default_dataset=f"{config.PROJECT}.{config.DATASET}")
        dry = client().query(sql, job_config=job_config)
        if dry.statement_type != "SELECT":
            raise QueryBlocked(f"Statement type {dry.statement_type} is not allowed.")
        if dry.total_bytes_processed > config.MAX_BYTES_PER_QUERY:
            raise QueryBlocked(f"Query would scan {dry.total_bytes_processed / 1e6:.0f} MB, over the "
                               f"{config.MAX_BYTES_PER_QUERY / 1e6:.0f} MB limit. Filter by date or aggregate more.")
    except QueryBlocked as err:
        audit(session_id, question, sql, "BLOCKED", str(err))
        raise
    except Exception as err:  # noqa: BLE001 - a SQL error is returned to the model so it can fix the query
        audit(session_id, question, sql, "ERROR", error_text(err)[:500])
        raise

    job = client().query(sql, job_config=bigquery.QueryJobConfig(
        default_dataset=f"{config.PROJECT}.{config.DATASET}", maximum_bytes_billed=config.MAX_BYTES_PER_QUERY,
        labels={"app": "freight-ai-analytics", "source": "ai-agent"}))
    result = job.result(max_results=config.MAX_ROWS_RETURNED + 1, timeout=60)
    columns = [f.name for f in result.schema]
    rows = [[_jsonable(v) for v in row.values()] for row in result]
    truncated = len(rows) > config.MAX_ROWS_RETURNED
    rows = rows[:config.MAX_ROWS_RETURNED]
    audit(session_id, question, sql, "ALLOWED", None, job.total_bytes_processed or 0, len(rows))
    return QueryResult(sql, columns, rows, job.total_bytes_processed or 0, truncated)


def _jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if v is not None and type(v).__name__ == "Decimal":
        return float(v)
    return v


def audit(session_id: str, question: str, sql: str | None, status: str, reason: str | None,
          bytes_processed: int = 0, rows: int = 0) -> None:
    try:
        errors = client().insert_rows_json(f"{config.PROJECT}.{config.DATASET}.ai_audit_log", [{
            "ts": datetime.now(timezone.utc).isoformat(), "session_id": session_id, "question": question[:2000],
            "sql": (sql or "")[:10000], "status": status, "reason": reason, "bytes_processed": bytes_processed,
            "rows_returned": rows, "model": config.AGENT_MODEL}])
        if errors:
            log.warning("Audit insert errors: %s", errors)
    except Exception:  # noqa: BLE001 - auditing must never break the request, but is logged
        log.exception("Audit log write failed")
