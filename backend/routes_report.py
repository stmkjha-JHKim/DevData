"""backend/routes_report.py -- "점검레포트"/Check Report button (next to
Refresh): unlike every other endpoint in this package, this one doesn't
hand its result back to the browser to download -- it saves the
generated HTML straight to disk under REPORT_DIR/<YYYY-MM-DD>/ (see
paths.py -- next to the .exe whenever that's writable, whether running
from source or as a portable frozen build, falling back to
%LOCALAPPDATA%\\OraPulse\\reports only when it isn't, e.g. a per-machine
MSI install to Program Files). That folder is created if missing (and
reused if it already exists) so a day's worth of reports land together
regardless of how many are generated. This replaced
a client-side "download the response as a Blob" flow that depended on the
browser's own download/Save-As handling actually completing -- saving
server-side works the same way regardless of browser download settings.

The report is a point-in-time inspection snapshot (see report.py's
generate_check_report()), not the old weekly-trend report: the moment
this endpoint is entered is recorded once as `click_dt` and used
consistently as both the report's own "reference time" and the output
filename -- see OraPulse_CheckReport_<click_dt>.html below."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from paths import REPORT_DIR
import report

from .core import Session, get_session

router = APIRouter()


def _today_date_folder(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _reserve_report_path(report_dir, base_filename: str):
    """Never overwrites an existing file: <name>.html, then <name>_2.html,
    <name>_3.html, ... until a free name is found. Collisions are only
    plausible within the same second (filename resolution is HHmmss), but
    still handled -- e.g. a double-click, or the button fired twice in
    quick succession."""
    stem, ext = os.path.splitext(base_filename)
    candidate = report_dir / base_filename
    n = 1
    while candidate.exists():
        n += 1
        candidate = report_dir / f"{stem}_{n}{ext}"
    return candidate


@router.post("/api/generate-report")
async def generate_report_endpoint(request: Request, session: Session = Depends(get_session)):
    # Recorded once, right here, before anything else runs -- this exact
    # instant is what the report calls its "reference time" and what the
    # filename is built from (requirement: click time recorded once, used
    # identically in both places). This endpoint is only ever reached
    # synchronously and immediately after the button click on the same
    # machine, so the small gap between the actual click and this line is
    # negligible; datetime.now() is OraPulse's own local execution-
    # environment time, exactly as specified.
    click_dt = datetime.now()

    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    lang = "ko" if body.get("lang") == "ko" else "en"

    try:
        html = await report.generate_check_report(creds, click_dt, lang)
    except Exception as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to generate report: {err}"}, status_code=500
        )

    filename = f"OraPulse_CheckReport_{click_dt.strftime('%Y%m%d_%H%M%S')}.html"
    date_folder = _today_date_folder(click_dt)
    report_dir = REPORT_DIR / date_folder
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        saved_path = _reserve_report_path(report_dir, filename)
        saved_path.write_text(html, encoding="utf-8")
    except OSError as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to save the report file: {err}"}, status_code=500
        )

    # Full path, not a relative "report/<date>/<file>" one -- REPORT_DIR
    # isn't always next to the .exe (see paths.py's writability fallback),
    # so a relative path alone wouldn't reliably tell the user where to look.
    full_path = str(saved_path)
    return {
        "success": True,
        "message": f"Check report saved: {saved_path.name}",
        "filename": saved_path.name,
        "path": full_path,
    }
