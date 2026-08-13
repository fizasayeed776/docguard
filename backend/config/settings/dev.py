from .base import *  # noqa: F401,F403

DEBUG = True
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_ALWAYS_EAGER", "false").lower() == "true"  # noqa: F405
