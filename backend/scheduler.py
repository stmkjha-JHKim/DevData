"""backend/scheduler.py -- runs enabled backup policies automatically.

APScheduler's BackgroundScheduler already executes each job in its own
worker thread (the default ThreadPoolExecutor), so calling
jobs.run_policy_sync() straight from a scheduled job is safe -- it's
already off the FastAPI/asyncio event loop, same as backend/datapump.py's
own docstring requires.

Rather than re-registering jobs from every policy CRUD endpoint, a single
reconciliation job runs every 60 seconds and re-derives the whole
schedule from the current BackupPolicy rows: adds/updates a job for every
enabled policy, removes one for anything disabled or deleted. Simpler
than keeping the scheduler in sync from N different call sites, at the
cost of policy edits taking up to ~60s to take effect -- fine for a
backup scheduler (nothing here needs sub-minute precision).
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.db import BackupPolicy, get_session
from backend.jobs import run_policy_sync

_scheduler = BackgroundScheduler(daemon=True)

_POLICY_JOB_PREFIX = "policy_"


def _trigger_for(policy: BackupPolicy):
    kind = (policy.schedule_kind or "DAILY").upper()
    if kind == "INTERVAL_HOURS":
        hours = policy.interval_hours or 24
        return IntervalTrigger(hours=hours)
    hour, minute = 3, 0
    if policy.schedule_time and ":" in policy.schedule_time:
        try:
            h, m = policy.schedule_time.split(":", 1)
            hour, minute = int(h), int(m)
        except ValueError:
            pass
    if kind == "WEEKLY":
        weekday = policy.schedule_weekday if policy.schedule_weekday is not None else 0
        return CronTrigger(day_of_week=weekday, hour=hour, minute=minute)
    return CronTrigger(hour=hour, minute=minute)  # DAILY, and the fallback for an unknown kind


def _run_scheduled(policy_id: str) -> None:
    run_policy_sync(policy_id, trigger="SCHEDULED")


def _reconcile() -> None:
    session = get_session()
    try:
        policies = {p.id: p for p in session.query(BackupPolicy).all()}
    finally:
        session.close()

    existing_job_ids = {
        job.id for job in _scheduler.get_jobs() if job.id.startswith(_POLICY_JOB_PREFIX)
    }
    wanted_job_ids = set()

    for policy_id, policy in policies.items():
        job_id = _POLICY_JOB_PREFIX + policy_id
        if not policy.enabled:
            continue
        wanted_job_ids.add(job_id)
        try:
            trigger = _trigger_for(policy)
        except Exception as err:
            print(f"[scheduler] skipping policy {policy.name} ({policy_id}): bad schedule ({err})")
            continue
        _scheduler.add_job(
            _run_scheduled, trigger=trigger, id=job_id, args=[policy_id],
            replace_existing=True, misfire_grace_time=3600, coalesce=True, max_instances=1,
        )

    for job_id in existing_job_ids - wanted_job_ids:
        _scheduler.remove_job(job_id)


def start_scheduler() -> None:
    if _scheduler.running:
        return
    _scheduler.add_job(_reconcile, trigger=IntervalTrigger(seconds=60), id="_reconcile", replace_existing=True)
    _scheduler.start()
    _reconcile()


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
