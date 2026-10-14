"""Draws three sample straight bills of lading (fictional companies) for the document demo:
1. clean, 2. with errors (missing freight class, totals that don't add up, no signature), 3. hazardous materials.
Run: python -m app.data.make_samples
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[2] / "samples"
FONT_PATHS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
HAND_PATHS = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", "/System/Library/Fonts/Noteworthy.ttc"]


def font(size: int, hand: bool = False) -> ImageFont.FreeTypeFont:
    for p in (HAND_PATHS if hand else []) + FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


SAMPLES = [
    {
        "file": "bol-1-clean.png", "bol": "BOL-4810233", "date": "2026-10-08",
        "shipper": ("Brightway Foods", "2100 Commerce Blvd", "Charlotte", "NC", "28208"),
        "consignee": ("FreshMart DC - Atlanta", "455 Distribution Way", "Atlanta", "GA", "30336"),
        "bill_to": "Brightway Foods - Freight Payables",
        "items": [(4, "PLT", 160, False, "Snack crackers, boxed", "149980", "60", 5240),
                  (2, "PLT", 80, False, "Pretzels, boxed", "149980", "65", 2310)],
        "total": 7550, "instructions": "Delivery appointment 10/09 06:00-08:00. Call receiving 24 hrs ahead.",
        "accessorials": ["APPOINTMENT"], "signed": True,
    },
    {
        "file": "bol-2-needs-review.png", "bol": "BOL-4810719", "date": "2026-10-09",
        "shipper": ("Cedar & Oak Furniture", "88 Mill Street", "Charlotte", "NC", "28206"),
        "consignee": ("HomeBase Hardware - Richmond", "1200 W Broad St", "Richmond", "VA", "23220"),
        "bill_to": None,
        "items": [(2, "CRT", 6, False, "Wood dining tables, crated", "82312", "", 840),
                  (1, "PLT", 12, False, "Upholstered chairs", "82280", "175", 410)],
        "total": 1450, "instructions": "Liftgate required. Fragile - do not stack.",
        "accessorials": ["LIFTGATE"], "signed": False, "hand": True,
    },
    {
        "file": "bol-3-hazmat.png", "bol": "BOL-4811052", "date": "2026-10-10",
        "shipper": ("Desert Sun Solar", "77 Solar Park Dr", "Phoenix", "AZ", "85043"),
        "consignee": ("Allied Mechanical - Dallas", "3300 Industrial Pkwy", "Dallas", "TX", "75207"),
        "bill_to": "Desert Sun Solar - Logistics",
        "items": [(1, "PLT", 24, True, "UN3480 Lithium ion batteries, 9, PG II", "60680", "85", 960),
                  (3, "PLT", 36, False, "Solar panels, boxed", "62290", "150", 1380)],
        "total": 2340, "instructions": "Emergency contact: CHEMTREC 800-424-9300. Inside delivery to dock 4.",
        "accessorials": ["INSIDE_DELIVERY"], "signed": True,
    },
]


def draw(s: dict) -> Image.Image:
    img = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(img)
    h1, h2, body, small = font(46), font(30), font(28), font(22)
    hand = font(34, hand=True) if s.get("hand") else body
    ink = (20, 30, 60)
    d.text((80, 70), "STRAIGHT BILL OF LADING - SHORT FORM", font=h1, fill="black")
    d.text((80, 135), "Original - Not Negotiable", font=small, fill="gray")
    d.rectangle((1150, 60, 1620, 190), outline="black", width=3)
    d.text((1170, 75), "BOL NUMBER", font=small, fill="gray")
    d.text((1170, 105), s["bol"], font=h2, fill=ink)
    d.text((1170, 150), f"Date: {s['date']}", font=body, fill=ink)

    def party(x, y, title, p):
        d.rectangle((x, y, x + 740, y + 250), outline="black", width=2)
        d.text((x + 15, y + 10), title, font=small, fill="gray")
        for i, line in enumerate([p[0], p[1], f"{p[2]}, {p[3]} {p[4]}"]):
            d.text((x + 15, y + 50 + i * 55), line, font=hand, fill=ink)

    party(80, 240, "SHIP FROM (SHIPPER)", s["shipper"])
    party(880, 240, "SHIP TO (CONSIGNEE)", s["consignee"])
    d.rectangle((80, 520, 1620, 600), outline="black", width=2)
    d.text((95, 530), "THIRD PARTY FREIGHT CHARGES BILL TO", font=small, fill="gray")
    d.text((95, 558), s["bill_to"] or "", font=body, fill=ink)

    d.rectangle((80, 630, 1620, 760), outline="black", width=2)
    d.text((95, 640), "SPECIAL INSTRUCTIONS", font=small, fill="gray")
    d.text((95, 680), s["instructions"], font=hand if s.get("hand") else body, fill=ink)

    cols = [(80, "UNITS"), (190, "TYPE"), (290, "PIECES"), (420, "HM"), (490, "DESCRIPTION"), (1080, "NMFC #"),
            (1250, "CLASS"), (1400, "WEIGHT (LBS)")]
    y = 800
    d.rectangle((80, y, 1620, y + 50), fill=(235, 238, 245), outline="black")
    for x, label in cols:
        d.text((x + 10, y + 12), label, font=small, fill="black")
    for units, ptype, pieces, hm, desc, nmfc, fclass, wt in s["items"]:
        y += 50
        d.rectangle((80, y, 1620, y + 70), outline="black")
        y += 10
        vals = [str(units), ptype, str(pieces), "X" if hm else "", desc, nmfc, fclass, f"{wt:,}"]
        for (x, _), v in zip(cols, vals):
            d.text((x + 10, y + 8), v, font=hand if s.get("hand") else body, fill=ink)
        y += 10
    y += 70
    d.text((1080, y), "TOTAL WEIGHT:", font=h2, fill="black")
    d.text((1400, y), f"{s['total']:,}", font=h2, fill=ink)

    y += 90
    d.text((80, y), "ACCESSORIAL SERVICES", font=small, fill="gray")
    for i, a in enumerate(["LIFTGATE", "RESIDENTIAL", "APPOINTMENT", "INSIDE_DELIVERY"]):
        x = 80 + i * 380
        d.rectangle((x, y + 40, x + 30, y + 70), outline="black", width=2)
        if a in s["accessorials"]:
            d.line((x + 4, y + 55, x + 13, y + 66), fill=ink, width=4)
            d.line((x + 13, y + 66, x + 28, y + 42), fill=ink, width=4)
        d.text((x + 45, y + 40), a.replace("_", " ").title(), font=body, fill="black")

    y += 140
    d.rectangle((80, y, 840, y + 180), outline="black", width=2)
    d.text((95, y + 10), "SHIPPER SIGNATURE / DATE", font=small, fill="gray")
    if s["signed"]:
        d.text((110, y + 70), "J. Ramirez   " + s["date"], font=font(44, hand=True), fill=(10, 30, 120))
    d.rectangle((880, y, 1620, y + 180), outline="black", width=2)
    d.text((895, y + 10), "CARRIER SIGNATURE / PICKUP DATE", font=small, fill="gray")
    d.text((895, y + 70), "Driver #4471   " + s["date"], font=font(40, hand=True), fill=(10, 30, 120))
    d.text((80, 2120), "Sample document for demonstration only. Fictional companies.", font=small, fill="gray")

    if s.get("hand"):  # a slightly skewed phone photo with uneven lighting
        img = img.rotate(random.uniform(-1.6, -1.0), expand=True, fillcolor=(240, 238, 232))
    return img


def main() -> None:
    random.seed(7)
    OUT.mkdir(exist_ok=True)
    for s in SAMPLES:
        draw(s).save(OUT / s["file"], optimize=True)
        print("wrote", OUT / s["file"])


if __name__ == "__main__":
    main()
