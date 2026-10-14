"""Freight analytics agent: answers business questions by writing and running governed BigQuery SQL.

Gemini decides the steps (agentic): check values, write SQL, read the result, fix the query if it fails or
returns nothing, drill down, then present an answer with a chart. Code enforces the guardrails: every SQL
statement goes through governance.run_query, the number of steps is capped, and every step is streamed to
the UI so people can see exactly what the AI did.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from google import genai
from google.genai import types

from . import config, governance, semantic

log = logging.getLogger(__name__)
_client = genai.Client(vertexai=True, project=config.PROJECT, location=config.VERTEX_LOCATION)
SESSIONS: dict[str, list[types.Content]] = {}   # short conversation memory for follow-up questions

TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="run_sql",
        description="Run one read-only BigQuery Standard SQL query against the approved views. Returns columns and "
                    "up to 500 rows. If it fails or is blocked, read the error and fix the query.",
        parameters_json_schema={"type": "object", "properties": {
            "sql": {"type": "string", "description": "SELECT query using only the approved v_ views"},
            "purpose": {"type": "string", "description": "One short sentence: what this query checks"}},
            "required": ["sql", "purpose"]}),
    types.FunctionDeclaration(
        name="present_answer",
        description="Finish: give the business answer and choose how to chart the most relevant query result.",
        parameters_json_schema={"type": "object", "properties": {
            "answer": {"type": "string", "description": "2-6 sentences: the headline finding with numbers, the likely "
                                                        "cause, and a practical next step. Plain business language."},
            "result_index": {"type": "integer", "description": "Which run_sql result to show (1 = first). Use the most informative one."},
            "chart_type": {"type": "string", "enum": ["bar", "line", "table"]},
            "x": {"type": "string", "description": "Column for the x axis / categories"},
            "y": {"type": "string", "description": "Numeric column to plot"},
            "title": {"type": "string"},
            "follow_ups": {"type": "array", "items": {"type": "string"}, "description": "2-3 useful follow-up questions"}},
            "required": ["answer", "result_index", "chart_type", "x", "y", "title", "follow_ups"]}),
])


def _system_prompt() -> str:
    return f"""You are a freight operations analyst for an LTL carrier. You answer questions from operations managers,
sales and customer service by querying BigQuery, then explain the result in plain business language.

Now is {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Shipments cover roughly the last 120 days and trailer telematics
the last 30 days. "Last week" means the last 7 full days.

Rules:
- Query only the approved views below; you may write bare names like v_shipments. Customer contact details are not
  available and must not be requested.
- Use the metric definitions exactly. Round rates to one decimal place as percentages in your answer.
- Prefer aggregated queries; never select more columns than you need.
- If a query fails, is blocked, or returns nothing, fix it and try again. Check categorical values first if unsure.
- For "why" questions, drill down: compare the period or terminal to others, look at delay_reason, lanes, hubs.
- For trailer questions, use v_trailer_positions for "now" and filter v_trailer_pings by time; link trailers to
  shipments and claims through v_trailer_trips and v_trailer_loads.
- This is BigQuery GoogleSQL: use FORMAT_DATE, DATE_TRUNC, EXTRACT, SAFE_DIVIDE (not STRFTIME or DATE_FORMAT).
- For trends, use complete periods only: end weekly series at the last full week and monthly at the last full month.
- Only state causes the data shows. If a cause is a guess (sales, demand, staffing), say it needs checking.
- Finish by calling present_answer exactly once. Do not invent numbers that no query returned.

{semantic.describe()}
"""


async def ask(question: str, session_id: str | None) -> AsyncIterator[dict]:
    """Yields progress events: step, sql, result, error, answer, done."""
    session_id = session_id or uuid.uuid4().hex[:12]
    history = SESSIONS.setdefault(session_id, [])
    contents = history[-8:] + [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    cfg = types.GenerateContentConfig(
        system_instruction=_system_prompt(), tools=[TOOLS], temperature=0.1,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    results: list[dict] = []
    yield {"type": "session", "sessionId": session_id, "model": config.AGENT_MODEL}

    for step in range(config.MAX_AGENT_STEPS):
        try:
            resp = await _client.aio.models.generate_content(model=config.AGENT_MODEL, contents=contents, config=cfg)
        except Exception as err:  # noqa: BLE001
            log.exception("Gemini call failed")
            yield {"type": "error", "message": f"Model call failed: {type(err).__name__}: {str(err)[:200]}"}
            return
        if not resp.candidates or not resp.candidates[0].content:
            yield {"type": "error", "message": "The model returned no answer (it may have been blocked by safety filters)."}
            return
        contents.append(resp.candidates[0].content)
        calls = resp.function_calls or []
        if not calls:  # answered in plain text without present_answer
            text = resp.text or "I couldn't produce an answer."
            yield {"type": "answer", "answer": text, "chart": None, "result": results[-1] if results else None, "followUps": []}
            _remember(session_id, question, text, results)
            return

        responses = []
        for call in calls:
            args = dict(call.args or {})
            if call.name == "run_sql":
                yield {"type": "step", "step": step + 1, "purpose": args.get("purpose", ""), "sql": args.get("sql", "")}
                try:
                    r = await asyncio.to_thread(governance.run_query, args.get("sql", ""), session_id, question)
                    entry = {"index": len(results) + 1, "sql": r.sql, "columns": r.columns, "rows": r.rows,
                             "bytes": r.bytes_processed, "truncated": r.truncated}
                    results.append(entry)
                    yield {"type": "result", **entry, "rows": r.rows[:50], "rowCount": len(r.rows)}
                    responses.append(types.Part.from_function_response(name="run_sql", response={
                        "result_index": entry["index"], "columns": r.columns, "rows": r.rows[:60],
                        "row_count": len(r.rows), "truncated": r.truncated}))
                except governance.QueryBlocked as err:
                    yield {"type": "blocked", "reason": str(err), "sql": args.get("sql", "")}
                    responses.append(types.Part.from_function_response(name="run_sql", response={"error": f"BLOCKED: {err}"}))
                except Exception as err:  # noqa: BLE001 - SQL errors go back to the model to self-correct
                    msg = governance.error_text(err)
                    yield {"type": "sql_error", "message": msg[:300]}
                    responses.append(types.Part.from_function_response(name="run_sql", response={"error": msg[:800]}))
            elif call.name == "present_answer":
                idx = int(args.get("result_index") or len(results) or 1)
                chosen = results[idx - 1] if 0 < idx <= len(results) else (results[-1] if results else None)
                chart = _chart(args, chosen)
                yield {"type": "answer", "answer": args.get("answer", ""), "chart": chart, "result": chosen,
                       "followUps": args.get("follow_ups", [])[:3], "queries": len(results)}
                _remember(session_id, question, args.get("answer", ""), results)
                return
            else:
                responses.append(types.Part.from_function_response(name=call.name, response={"error": "unknown tool"}))
        contents.append(types.Content(role="user", parts=responses))

    yield {"type": "error", "message": f"Stopped after {config.MAX_AGENT_STEPS} steps without a final answer."}


def _chart(args: dict, result: dict | None) -> dict | None:
    if not result or args.get("chart_type") == "table":
        return {"type": "table", "title": args.get("title", "")} if result else None
    x, y = args.get("x"), args.get("y")
    if x not in result["columns"] or y not in result["columns"]:
        return {"type": "table", "title": args.get("title", "")}
    return {"type": args.get("chart_type", "bar"), "x": x, "y": y, "title": args.get("title", "")}


def _remember(session_id: str, question: str, answer: str, results: list[dict]) -> None:
    """Keeps a compact text history (question, SQL used, answer) so follow-ups like 'why?' have context."""
    sql = "\n".join(r["sql"] for r in results[-2:])
    SESSIONS[session_id] = (SESSIONS.get(session_id, []) + [
        types.Content(role="user", parts=[types.Part.from_text(text=question)]),
        types.Content(role="model", parts=[types.Part.from_text(text=f"{answer}\n\n(SQL used:\n{sql})")]),
    ])[-8:]


def to_ndjson(event: dict) -> bytes:
    return (json.dumps(event, default=str) + "\n").encode()
