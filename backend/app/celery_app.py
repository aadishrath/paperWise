from celery import Celery

from app.config import get_settings

settings = get_settings()
celery = Celery("paperwise", broker=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
celery.autodiscover_tasks(["app"])
