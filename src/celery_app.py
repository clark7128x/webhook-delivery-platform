import os
from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

@celery_setup_logging.connect
def setup_celery_logging(**kwargs):
    from .logger import setup_logging
    setup_logging()

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

app = Celery("webhook_platform", broker=broker_url, backend=result_backend)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=os.getenv("CELERY_ALWAYS_EAGER", "False") == "True"
)

app.autodiscover_tasks(["src"])
