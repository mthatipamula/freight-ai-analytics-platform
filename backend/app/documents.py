"""Bill of lading reader: Gemini reads a scanned or photographed BOL and returns structured fields (JSON schema),
then code validates them against freight rules before anything is saved to BigQuery.

Gen AI, not an agent: one well-defined input and output, so a single model call with a strict schema is cheaper,
faster and easier to test than an agent loop.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone

from google import genai
from google.cloud import bigquery
from google.genai import types
from pydantic import BaseModel, Field

from . import config, governance

log = logging.getLogger(__name__)
_client = genai.Client(vertexai=True, project=config.PROJECT, location=config.VERTEX_LOCATION)

# NMFC freight classes. Anything else is a data-entry error.
VALID_CLASSES = {"50", "55", "60", "65", "70", "77.5", "85", "92.5", "100", "110", "125", "150", "175", "200", "250",
                 "300", "400", "500"}
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}


class Party(BaseModel):
    name: str = Field(description="Company or person name")
    address: str = Field(description="Street address")
    city: str
    state: str = Field(description="2-letter state code")
    zip: str


class LineItem(BaseModel):
    handling_units: int | None = Field(description="Pallets or handling units; null if not shown")
    package_type: str | None = Field(description="e.g. PLT, CTN, CRT")
    pieces: int | None
    description: str
    nmfc: str | None = Field(description="NMFC item number if shown")
    freight_class: str | None = Field(description="Freight class exactly as written; null if blank")
    weight_lbs: float | None
    hazmat: bool = Field(description="True if the HM column is marked")


class BillOfLading(BaseModel):
    bol_number: str | None
    ship_date: str | None = Field(description="YYYY-MM-DD")
    shipper: Party
    consignee: Party
    bill_to: str | None = Field(description="Third-party bill-to name, if any")
    line_items: list[LineItem]
    stated_total_weight_lbs: float | None = Field(description="Total weight as written on the form")
    special_instructions: str | None
    accessorials: list[str] = Field(description="Checked services, e.g. LIFTGATE, RESIDENTIAL, APPOINTMENT, INSIDE_DELIVERY")
    shipper_signed: bool
    legibility_notes: str | None = Field(description="Anything hard to read or ambiguous")


PROMPT = """Extract the fields from this straight bill of lading (LTL freight shipping document).
Copy values exactly as written. If a field is blank or unreadable, return null and mention it in legibility_notes.
Do not guess freight classes or weights."""


def validate(bol: BillOfLading) -> list[str]:
    issues = []
    if not bol.bol_number:
        issues.append("Missing BOL number")
    try:
        if bol.ship_date:
            date.fromisoformat(bol.ship_date)
        else:
            issues.append("Missing ship date")
    except ValueError:
        issues.append(f"Ship date '{bol.ship_date}' is not a valid date")
    if not bol.line_items:
        issues.append("No line items")
    for i, item in enumerate(bol.line_items, 1):
        if not item.freight_class:
            issues.append(f"Line {i}: freight class is missing (needed to rate the shipment)")
        elif item.freight_class.strip() not in VALID_CLASSES:
            issues.append(f"Line {i}: '{item.freight_class}' is not a valid NMFC freight class")
        if not item.weight_lbs or item.weight_lbs <= 0:
            issues.append(f"Line {i}: weight is missing")
    line_total = sum(i.weight_lbs or 0 for i in bol.line_items)
    if bol.stated_total_weight_lbs and abs(line_total - bol.stated_total_weight_lbs) > 1:
        issues.append(f"Line weights add up to {line_total:,.0f} lbs but the total says {bol.stated_total_weight_lbs:,.0f} lbs")
    if any(i.hazmat for i in bol.line_items) and not (bol.special_instructions and "emergency" in bol.special_instructions.lower()):
        issues.append("Hazardous materials declared but no emergency contact in special instructions")
    if not bol.shipper_signed:
        issues.append("Shipper signature missing")
    if bol.legibility_notes:
        issues.append(f"Check legibility: {bol.legibility_notes}")
    return issues


async def extract(content: bytes, mime_type: str, file_name: str) -> dict:
    if mime_type not in ALLOWED_TYPES:
        raise ValueError("Upload a PNG, JPEG, WEBP or PDF file")
    resp = await _client.aio.models.generate_content(
        model=config.FAST_MODEL,
        contents=[types.Part.from_bytes(data=content, mime_type=mime_type), PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=BillOfLading,
                                           temperature=0))
    bol: BillOfLading = resp.parsed if isinstance(resp.parsed, BillOfLading) else BillOfLading.model_validate_json(resp.text)
    issues = validate(bol)
    doc = {
        "document_id": uuid.uuid4().hex[:12], "uploaded_at": datetime.now(timezone.utc).isoformat(), "file_name": file_name[:200],
        "status": "NEEDS_REVIEW" if issues else "READY", "bol_number": bol.bol_number,
        "ship_date": bol.ship_date if bol.ship_date and "Ship date" not in " ".join(issues) else None,
        "shipper_name": bol.shipper.name, "shipper_address": f"{bol.shipper.address}, {bol.shipper.city}, {bol.shipper.state} {bol.shipper.zip}",
        "consignee_name": bol.consignee.name,
        "consignee_address": f"{bol.consignee.address}, {bol.consignee.city}, {bol.consignee.state} {bol.consignee.zip}",
        "consignee_city": bol.consignee.city, "consignee_state": bol.consignee.state,
        "total_pieces": sum(i.pieces or 0 for i in bol.line_items),
        "total_weight_lbs": sum(i.weight_lbs or 0 for i in bol.line_items),
        "freight_classes": [i.freight_class for i in bol.line_items if i.freight_class],
        "hazmat": any(i.hazmat for i in bol.line_items), "accessorials": [a.upper() for a in bol.accessorials],
        "issues": issues, "extracted_json": json.dumps(bol.model_dump()), "model": config.FAST_MODEL, "reviewed_by": None,
    }
    # A load job (not a streaming insert) so the row can be updated right away when a person approves it.
    job = governance.client().load_table_from_json(
        [doc], f"{config.PROJECT}.{config.DATASET}.bills_of_lading",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()
    return {**doc, "extracted": bol.model_dump()}


def approve(document_id: str, reviewer: str) -> None:
    governance.client().query(
        f"UPDATE {config.table('bills_of_lading')} SET status = 'APPROVED', reviewed_by = @r WHERE document_id = @id",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("r", "STRING", reviewer),
            bigquery.ScalarQueryParameter("id", "STRING", document_id)])).result()


def recent(limit: int = 25) -> list[dict]:
    rows = governance.client().query(
        f"""SELECT document_id, uploaded_at, file_name, status, bol_number, shipper_name, consignee_name, total_pieces,
                   total_weight_lbs, freight_classes, hazmat, accessorials, issues, reviewed_by
            FROM {config.table('bills_of_lading')} ORDER BY uploaded_at DESC LIMIT {int(limit)}""").result()
    return [{k: governance._jsonable(v) for k, v in dict(r).items()} for r in rows]
