"""backend/routes_report.py -- Weekly DB Health Report (Report button next
to Refresh): unlike every other endpoint in this package, this one
doesn't hand its result back to the browser to download -- it saves the
generated HTML straight to disk, next to the running .exe (app_dir()),
under report/<YYYY-MM-DD>/. That folder is created if missing (and reused
if it already exists) so a day's worth of reports land together
regardless of how many are generated. This replaced a client-side
"download the response as a Blob" flow that depended on the browser's own
download/Save-As handling actually completing -- saving server-side works
the same way regardless of browser download settings."""

import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from paths import app_dir
import report

from .core import Session, get_session

router = APIRouter()

_FILENAME_SANITIZE_RE = re.compile(r'[\\/:*?"<>|]')


def _today_date_folder() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@router.post("/api/generate-report")
async def generate_report_endpoint(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    try:
        days = int(body.get("days"))
    except (TypeError, ValueError):
        days = 7
    if days <= 0:
        days = 7
    if days > 30:
        days = 30

    lang = "ko" if body.get("lang") == "ko" else "en"

    # Only the base name is ever used -- a client-supplied path (or "..")
    # must never be able to steer where this gets written on disk.
    filename = os.path.basename(str(body.get("filename") or "").strip())
    filename = _FILENAME_SANITIZE_RE.sub("_", filename)
    if not filename or filename in (".", ".."):
        filename = f"orapulse-report-{datetime.now().strftime('%Y%m%d')}.html"
    if not filename.lower().endswith((".html", ".htm")):
        filename += ".html"

    try:
        html = await report.generate_report(creds, days, lang)
    except Exception as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to generate report: {err}"}, status_code=500
        )

    date_folder = _today_date_folder()
    report_dir = app_dir() / "report" / date_folder
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / filename).write_text(html, encoding="utf-8")
    except OSError as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to save report file: {err}"}, status_code=500
        )

    rel_path = f"report/{date_folder}/{filename}"
    return {"success": True, "message": f"Report saved to {rel_path}", "path": rel_path}
