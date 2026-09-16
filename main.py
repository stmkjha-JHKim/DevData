"""main.py -- entry point: creates the app, registers routes, launches the
server. Same overall shape as OraPulse's own main.py (FastAPI + uvicorn,
static frontend served straight out of public/), extended with the local
SQLite metadata store and the backup scheduler this project adds on top.

Run from source:
    pip install -r requirements.txt
    python main.py
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.core import APP_VERSION, HOST, PORT
from backend.db import init_db
from backend.scheduler import shutdown_scheduler, start_scheduler
from paths import PUBLIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="OraPulse Backup", version=APP_VERSION, lifespan=lifespan)

from backend.routes_dashboard import router as dashboard_router
from backend.routes_db import router as dbs_router
from backend.routes_history import router as history_router
from backend.routes_policies import router as policies_router
from backend.routes_recovery import router as recovery_router

app.include_router(dbs_router)
app.include_router(policies_router)
app.include_router(history_router)
app.include_router(dashboard_router)
app.include_router(recovery_router)


@app.get("/api/version")
async def version():
    return {"success": True, "version": APP_VERSION}


@app.get("/")
async def root():
    return RedirectResponse(url="/index.html")


# Static frontend -- mounted last so it doesn't shadow the /api/* routes
# above. html=True lets /index.html and /dashboard.html resolve without
# the extension too, matching how OraPulse's own public/ is served.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


def main():
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
