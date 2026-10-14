"""Freight AI Analytics Platform API."""
import asyncio
import logging
import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import agent, config, documents, governance, semantic, trailers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="Freight AI Analytics Platform", version="1.0.0")
SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MAX_UPLOAD = 10 * 1024 * 1024


def _rows(sql: str) -> list[dict]:
    return [{k: governance._jsonable(v) for k, v in dict(r).items()} for r in governance.client().query(sql).result()]


@app.get("/health")
async def health():
    return {"status": "UP", "project": config.PROJECT, "dataset": config.DATASET,
            "agentModel": config.AGENT_MODEL, "fastModel": config.FAST_MODEL}


@app.get("/api/overview")
async def overview():
    """Fixed KPI queries (not AI-generated) for the landing page."""
    v = lambda n: config.table(n)  # noqa: E731
    kpis = await asyncio.to_thread(_rows, f"""
        SELECT COUNT(*) AS shipments,
               ROUND(100 * AVG(IF(status = 'DELIVERED', IF(on_time, 1, 0), NULL)), 1) AS on_time_pct,
               ROUND(SUM(revenue_usd)) AS revenue,
               COUNTIF(status = 'IN_TRANSIT') AS in_transit
        FROM {v('v_shipments')} WHERE pickup_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)""")
    claims = await asyncio.to_thread(_rows, f"""
        SELECT COUNT(*) AS claims, COUNTIF(status = 'OPEN') AS open_claims, ROUND(SUM(amount_usd)) AS claim_amount
        FROM {v('v_claims')} WHERE filed_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)""")
    return {**kpis[0], **claims[0], "window": "last 30 days"}


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    session_id: str | None = Field(default=None, max_length=40)


@app.post("/api/ask")
async def ask(body: Ask):
    async def stream():
        async for event in agent.ask(body.question, body.session_id):
            yield agent.to_ndjson(event)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/catalog")
async def catalog():
    return {"views": semantic.VIEWS, "metrics": semantic.METRICS, "glossary": semantic.GLOSSARY}


@app.post("/api/documents")
async def upload(file: UploadFile = File(...)):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 10 MB")
    try:
        return await documents.extract(content, file.content_type or "", file.filename or "upload")
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@app.get("/api/documents")
async def list_documents():
    return await asyncio.to_thread(documents.recent)


@app.post("/api/documents/{document_id}/approve")
async def approve(document_id: str):
    if not document_id.isalnum() or len(document_id) > 20:
        raise HTTPException(400, "Bad document id")
    await asyncio.to_thread(documents.approve, document_id, "operations-reviewer")
    return {"documentId": document_id, "status": "APPROVED"}


@app.get("/api/samples")
async def samples():
    return sorted(p.name for p in SAMPLES.glob("*.png"))


@app.get("/api/samples/{name}")
async def sample(name: str):
    path = (SAMPLES / name).resolve()
    if path.parent != SAMPLES.resolve() or not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/governance")
async def governance_view():
    log_rows = await asyncio.to_thread(_rows, f"""
        SELECT ts, question, sql, status, reason, bytes_processed, rows_returned
        FROM {config.table('ai_audit_log')} ORDER BY ts DESC LIMIT 50""")
    totals = await asyncio.to_thread(_rows, f"""
        SELECT status, COUNT(*) AS n, SUM(bytes_processed) AS bytes FROM {config.table('ai_audit_log')}
        WHERE ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) GROUP BY status""")
    return {"policy": {"allowedViews": sorted(config.ALLOWED_VIEWS), "maxBytesPerQuery": config.MAX_BYTES_PER_QUERY,
                       "maxRows": config.MAX_ROWS_RETURNED, "readOnly": True,
                       "maskedFields": ["consignee contact name, phone and email (not in any view)",
                                        "residential consignee names (shown as 'Residential customer')"]},
            "totals": totals, "log": log_rows}


@app.get("/api/trailers")
async def trailer_positions():
    positions, terminals = await asyncio.gather(asyncio.to_thread(trailers.positions), asyncio.to_thread(trailers.sites))
    return {"trailers": positions, "terminals": terminals}


@app.get("/api/trailers/alerts")
async def trailer_alerts():
    return await asyncio.to_thread(trailers.alerts)


@app.get("/api/trailers/{trailer_id}")
async def trailer_trail(trailer_id: str, hours: int = 72):
    if not re.fullmatch(r"[A-Z]\d{6}", trailer_id):
        raise HTTPException(400, "Bad trailer id")
    return await asyncio.to_thread(trailers.trail, trailer_id, max(1, min(hours, 720)))
