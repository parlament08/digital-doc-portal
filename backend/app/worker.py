import asyncio
import hashlib
import os
from datetime import datetime, timedelta
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from temporalio.common import RetryPolicy

# Импорты из нашего проекта
from app.services.pdf_generator import PDFGenerator
from app.services.storage import MinioService
from app.core.database import SessionLocal
from app.models.audit import AuditTrail

# 1. ACTIVITY (Сама работа)
# Здесь происходит то, что раньше делал FastAPI: генерация PDF и запись в базу
@activity.defn
async def generate_document_activity(data: dict) -> dict:
    print(f"[{datetime.now()}] Начинаю генерацию PDF для: {data['employee_name']}")
    
    pdf_gen = PDFGenerator()
    storage = MinioService()
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # Генерируем PDF
    pdf_bytes = await pdf_gen.create_safety_doc(
        employee_name=data["employee_name"],
        doc_id=data["doc_id"],
        date=current_date
    )
    
    doc_hash = hashlib.sha256(pdf_bytes).hexdigest()
    file_name = f"safety/{current_date[-4:]}/{data['doc_id']}.pdf"
    file_path = storage.upload_pdf(file_name, pdf_bytes)
    
    # Обновляем статус в базе данных
    db = SessionLocal()
    try:
        # Ищем ту самую "заглушку" со статусом GENERATION_IN_PROGRESS
        audit_record = db.query(AuditTrail).filter(AuditTrail.document_id == data["doc_id"]).first()
        if audit_record:
            audit_record.event_type = "DOCUMENT_SIGNED_PEP"
            audit_record.document_hash = doc_hash
            
            # Обновляем JSON с метаданными
            meta = dict(audit_record.metadata_info)
            meta["minio_path"] = file_path
            meta["status"] = "success"
            audit_record.metadata_info = meta
            
            db.commit()
            print(f"[{datetime.now()}] Успех! Документ {data['doc_id']} сохранен.")
    finally:
        db.close()
        
    return {"document_hash": doc_hash, "minio_path": file_path}

# 2. WORKFLOW (Оркестратор)
# Он говорит Temporal, как именно запускать Activity (таймауты, ретраи)
@workflow.defn
class DocumentWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        return await workflow.execute_activity(
            generate_document_activity,
            data,
            start_to_close_timeout=timedelta(seconds=60), # Ждем максимум минуту
            retry_policy=RetryPolicy(maximum_attempts=3)  # Если Playwright упадет, пробуем еще 3 раза!
        )

# 3. ЗАПУСК ВОРКЕРА
async def main():
    # Берем адрес из переменных окружения (в докере это temporal:7233)
    temporal_url = os.getenv("TEMPORAL_URL", "temporal:7233")
    client = await Client.connect(temporal_url)
    
    worker = Worker(
        client,
        task_queue="document-generation-queue",
        workflows=[DocumentWorkflow],
        activities=[generate_document_activity],
        workflow_runner=UnsandboxedWorkflowRunner(), # <-- ОТКЛЮЧАЕМ ПЕСОЧНИЦУ
    )
    
    print("🚀 Temporal Worker успешно запущен и ждет задач...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())