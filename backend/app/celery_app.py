import os
from celery import Celery

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/doc_portal")

# Магия sqla+: говорим Celery использовать SQLAlchemy для общения с Postgres
broker_url = f"sqla+{DATABASE_URL}"
result_backend = f"db+{DATABASE_URL}"

celery_app = Celery(
    "digital_doc_worker",
    broker=broker_url,
    backend=result_backend,
    include=['app.worker']  # Указываем, где лежат наши фоновые задачи
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Europe/Chisinau',  # Локальное время для корректных логов
    enable_utc=True,
)