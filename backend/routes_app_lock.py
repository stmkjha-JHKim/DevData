"""backend/routes_app_lock.py -- the three endpoints behind public/lock.html
(status/setup/verify) plus the HTTP middleware that actually enforces the
app-password gate for every other request this server receives.

See app_lock.py's own top-of-file comment for the full design rationale
(why this is a gate and not a data-encryption key, why the unlock session
is separate from the DB connection's own session, etc.) -- this module is
just the HTTP-shaped wiring around it.

Allow-list kept intentionally tiny (LOCK_ALLOWED_API_PATHS below): only
what's needed to render the lock screen and complete setup/unlock, plus
/api/version, which has to stay reachable pre-unlock for an unrelated
reason -- main.py's own single-instance detection (_running_instance_url())
polls another already-running OraPulse process's /api/version to decide
whether to hand off to it instead of starting a second server. If that
call started failing while the first instance is sitting locked, every
relaunch would think no instance is running and start a redundant second
server/tray icon. /api/version only ever reveals this app's own version
string, never anything about the DB or local data, so allowing it
unauthenticated doesn't weaken the gate.

Session/cookie/CSRF notes (reviewed against this app's own access model, not
a generic hosted-webapp checklist -- see main.py's top-of-file comment for
why the usual internet-facing hardening doesn't apply here):
  - The unlock cookie is httponly (never readable from page JS -- closes
    off the obvious XSS-reads-the-cookie path) and samesite="lax", the same
    flags backend/core.py's own DB-session cookie already uses. No
    `secure` flag, same reason core.py's cookie doesn't set one either:
    this server is only ever reached over plain http://127.0.0.1, which
    never gets TLS, so `secure` would just silently stop the cookie from
    being sent at all.
  - CSRF: SameSite=Lax is the actual mitigation here, not a CSRF token --
    modern browsers withhold a Lax cookie from a cross-site POST (whether
    via fetch/XHR or an auto-submitting hidden form), which covers the one
    scenario that matters for a 127.0.0.1-bound app: some other page open
    in another tab on this *same machine* trying to POST to this origin.
    There is no cross-*site* GET-based state change anywhere in this API
    (every mutating endpoint -- setup/verify included -- is POST-only) for
    SameSite=Lax's narrower GET-allowance to matter.
  - Input validation: both JSON bodies here are parsed inside a try/except
    (a malformed body is a 400, never a 500/stack trace), and
    app_lock.validate_new_password()/verify_password() both type-check and
    length-cap the password before it ever reaches PBKDF2 -- see
    app_lock.py's own MAX_PASSWORD_LENGTH.
"""

from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

import app_lock
from .core import PUBLIC_DIR, app

router = APIRouter()

# Read once at import time -- public/lock.html is a bundled, read-only
# resource (see paths.py's resource_dir()/PUBLIC_DIR), never rewritten at
# runtime, same assumption index.html/dashboard.html already rely on.
_LOCK_PAGE_HTML = (PUBLIC_DIR / "lock.html").read_text(encoding="utf-8")

LOCK_ALLOWED_API_PATHS = {
    "/api/version",
    "/api/app-lock/status",
    "/api/app-lock/setup",
    "/api/app-lock/verify",
}


def _set_unlock_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        app_lock.UNLOCK_COOKIE_NAME,
        token,
        httponly=True,
        max_age=app_lock.UNLOCK_IDLE_SECONDS,
        samesite="lax",
    )


@router.get("/api/app-lock/status")
async def app_lock_status():
    return {"success": True, "configured": app_lock.is_configured()}


@router.post("/api/app-lock/setup")
async def app_lock_setup(request: Request, response: Response):
    # Never allowed to overwrite an existing password -- this endpoint has
    # to stay reachable *before* unlocking (so a first run can set one up
    # at all), which would otherwise let anyone who can reach this server
    # silently replace an already-configured password without ever
    # providing the old one, defeating the gate entirely.
    if app_lock.is_configured():
        return JSONResponse(
            {"success": False, "message": "이미 앱 비밀번호가 설정되어 있습니다."}, status_code=409
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "message": "잘못된 요청입니다."}, status_code=400)

    password = body.get("password")
    confirm_password = body.get("confirmPassword")
    error = app_lock.validate_new_password(password, confirm_password)
    if error:
        return JSONResponse({"success": False, "message": error}, status_code=400)

    app_lock.set_password(password)
    app_lock.register_success()
    token = app_lock.create_unlock_token()
    _set_unlock_cookie(response, token)
    return {"success": True}


@router.post("/api/app-lock/verify")
async def app_lock_verify(request: Request, response: Response):
    if not app_lock.is_configured():
        return JSONResponse(
            {"success": False, "message": "아직 앱 비밀번호가 설정되지 않았습니다."}, status_code=409
        )

    remaining = app_lock.lockout_remaining_seconds()
    if remaining > 0:
        return JSONResponse(
            {
                "success": False,
                "message": f"시도 횟수가 많습니다. {int(remaining) + 1}초 후 다시 시도하세요.",
                "retryAfterSeconds": round(remaining, 1),
            },
            status_code=429,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "message": "잘못된 요청입니다."}, status_code=400)

    password = body.get("password")
    if app_lock.verify_password(password):
        app_lock.register_success()
        token = app_lock.create_unlock_token()
        _set_unlock_cookie(response, token)
        return {"success": True}

    app_lock.register_failure()
    return JSONResponse({"success": False, "message": "비밀번호가 올바르지 않습니다."}, status_code=401)


# --- The gate itself ---
#
# Runs ahead of routing entirely (Starlette middleware wraps the whole
# ASGI app, including the StaticFiles mount main.py adds for public/), so
# this is the one place that has to reason about every path this server
# can possibly serve -- not just /api/*. See the module docstring for why
# the allow-list is this small.
@app.middleware("http")
async def app_lock_gate(request: Request, call_next):
    path = request.url.path
    if path in LOCK_ALLOWED_API_PATHS:
        return await call_next(request)

    configured = app_lock.is_configured()
    token: Optional[str] = request.cookies.get(app_lock.UNLOCK_COOKIE_NAME)
    unlocked = configured and app_lock.is_unlocked(token)

    if unlocked:
        response = await call_next(request)
        # Refresh the cookie's own Max-Age alongside the sliding server-side
        # expiry is_unlocked() already extended above, so the two stay in
        # sync -- without this, the browser would still drop the cookie
        # after the *original* max_age even during continuous active use.
        _set_unlock_cookie(response, token)
        return response

    if path.startswith("/api/"):
        return JSONResponse(
            {
                "success": False,
                "message": "앱 비밀번호 설정 또는 확인이 필요합니다.",
                "needsSetup": not configured,
            },
            status_code=401,
        )

    # Any other request (the connect screen, the dashboard, a static asset)
    # gets the same self-contained lock screen instead of what it actually
    # asked for -- see public/lock.html's own script for how it decides
    # between "set up a new password" and "unlock" using the status
    # endpoint above.
    return HTMLResponse(_LOCK_PAGE_HTML, status_code=200)
