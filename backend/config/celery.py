import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("docguard")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Celery Beat schedule: nightly full scan, weekly digest, hourly freshness check.
app.conf.beat_schedule = {
    "nightly-full-scan": {
        "task": "apps.agents.tasks.run_full_scan_all_workspaces",
        "schedule": crontab(hour=2, minute=0),
    },
    "weekly-digest": {
        "task": "apps.automation.tasks.send_weekly_digest",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),  # Monday 08:00
    },
    "hourly-source-freshness-check": {
        "task": "apps.sources.tasks.check_source_freshness",
        "schedule": crontab(minute=0),
    },
}
