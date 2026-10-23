"""Background jobs: the Friday weekly report and the scheduled JIRA / ADO status sync.

Runs inside the web process (APScheduler). With more than one web worker, set
SCHEDULER_ENABLED=false on all but one of them so jobs don't run twice.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger("app.scheduler")
_scheduler: BackgroundScheduler | None = None


def weekly_report_job() -> None:
    from app.reports.weekly import generate_weekly_report, previous_week

    with SessionLocal() as db:
        start, end = previous_week()
        report = generate_weekly_report(db, None, start, end)
        db.commit()
        logger.info("Weekly report %s generated (%s)", report.id, report.title)


def integration_sync_job() -> None:
    from app.integrations.service import run_scheduled_sync

    with SessionLocal() as db:
        for name, summary in run_scheduled_sync(db):
            logger.info("Sync %s: %s", name, summary)


def start() -> None:
    global _scheduler
    if _scheduler is not None or not settings.SCHEDULER_ENABLED:
        return
    _scheduler = BackgroundScheduler(timezone=None)
    _scheduler.add_job(weekly_report_job, CronTrigger(day_of_week=settings.WEEKLY_REPORT_DAY,
                                                      hour=settings.WEEKLY_REPORT_HOUR, minute=0),
                       id="weekly_report", replace_existing=True, misfire_grace_time=3600, coalesce=True)
    _scheduler.add_job(integration_sync_job, IntervalTrigger(minutes=settings.SYNC_INTERVAL_MINUTES),
                       id="integration_sync", replace_existing=True, coalesce=True, max_instances=1)
    _scheduler.start()
    logger.info("Scheduler started")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def jobs() -> list[dict]:
    if _scheduler is None:
        return []
    return [{"id": j.id, "next_run": j.next_run_time} for j in _scheduler.get_jobs()]
