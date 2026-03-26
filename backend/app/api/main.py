import os
import uuid
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from app.services.storage import MinioService

# Импорт клиента Temporal
from temporalio.client import Client

# База данных и модели
from app.core.database import get_db, engine
from app.models.audit import Base, AuditTrail

# Создаем таблицы
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Digital Doc Portal (MVP)",
    description="Внутренний портал документооборота с ЭЦП/ПЭП",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SafetyDocRequest(BaseModel):
    employee_name: str
    user_id: str 

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "API работает. Задачи уходят в Temporal."}

@app.get("/documents/{user_id}", summary="Получить список подписанных документов")
def get_user_documents(user_id: str, db: Session = Depends(get_db)):
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат user_id")

    records = db.query(AuditTrail).filter(
        AuditTrail.user_id == user_uuid,
        AuditTrail.event_type == "DOCUMENT_SIGNED_PEP"
    ).order_by(AuditTrail.id.desc()).all()

    documents = []
    for record in records:
        documents.append({
            "audit_id": record.id,
            "document_id": str(record.document_id),
            "document_hash": record.document_hash,
            "action": record.metadata_info.get("action", "Подписан документ"),
            "minio_path": record.metadata_info.get("minio_path", "")
        })

    return {"status": "success", "total": len(documents), "documents": documents}

@app.post("/generate-safety-doc", summary="Запуск фоновой генерации документа")
async def generate_safety_doc(req: SafetyDocRequest, request: Request, db: Session = Depends(get_db)):
    try:
        user_uuid = uuid.UUID(req.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат user_id.")

    try:
        # === 1. ПРОВЕРКА БЛОКИРОВОК ===
        existing_audit = db.query(AuditTrail).filter(
            AuditTrail.user_id == user_uuid,
            AuditTrail.event_type.in_(["DOCUMENT_SIGNED_PEP", "GENERATION_IN_PROGRESS"])
        ).first()

        if existing_audit:
            if existing_audit.event_type == "GENERATION_IN_PROGRESS":
                return {"status": "processing", "message": "Документ уже формируется в фоне. Пожалуйста, подождите."}
            else:
                return {
                    "status": "success",
                    "message": "Документ УЖЕ БЫЛ подписан ранее",
                    "document_id": str(existing_audit.document_id),
                    "document_hash": existing_audit.document_hash,
                    "audit_id": existing_audit.id
                }

        # === 2. СТАВИМ БЛОКИРОВКУ ===
        doc_id = str(uuid.uuid4())
        client_ip = request.client.host if request.client else "unknown"
        
        audit_record = AuditTrail(
            event_type="GENERATION_IN_PROGRESS",
            user_id=user_uuid,
            document_id=doc_id,
            document_hash="pending",
            metadata_info={"ip_address": client_ip, "status": "generating"}
        )
        db.add(audit_record)
        db.commit()
        db.refresh(audit_record)

        # === 3. ОТПРАВЛЯЕМ ЗАДАЧУ В TEMPORAL (МАГИЯ ЗДЕСЬ) ===
        temporal_url = os.getenv("TEMPORAL_URL", "temporal:7233")
        temporal_client = await Client.connect(temporal_url)

        # start_workflow НЕ ждет завершения. Он просто кидает задачу и сразу идет дальше.
        await temporal_client.start_workflow(
            "DocumentWorkflow", # Имя нашего класса из worker.py
            {
                "employee_name": req.employee_name,
                "doc_id": doc_id
            },
            id=f"doc-gen-{doc_id}",
            task_queue="document-generation-queue",
        )
        
        # === 4. МОМЕНТАЛЬНЫЙ ОТВЕТ ФРОНТЕНДУ ===
        return {
            "status": "processing",
            "message": "Документ отправлен на генерацию в фоне 🚀",
            "document_id": doc_id,
            "document_hash": "Будет доступен после генерации",
            "audit_id": audit_record.id
        }
        
    except Exception as e:
        if 'audit_record' in locals():
            db.delete(audit_record)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/download/{audit_id}", summary="Скачать подписанный PDF")
def download_document(audit_id: int, db: Session = Depends(get_db)):
    # Ищем запись
    record = db.query(AuditTrail).filter(AuditTrail.id == audit_id).first()
    if not record or "minio_path" not in record.metadata_info:
        raise HTTPException(status_code=404, detail="Файл не найден")
        
    file_path = record.metadata_info["minio_path"]
    bucket_name = "signed-documents"
    
    # ОЧИСТКА ПУТИ: убираем имя бакета, если оно случайно приклеилось в начале
    if file_path.startswith(f"/{bucket_name}/"):
        file_path = file_path.replace(f"/{bucket_name}/", "", 1)
    elif file_path.startswith(f"{bucket_name}/"):
        file_path = file_path.replace(f"{bucket_name}/", "", 1)
        
    storage = MinioService()
    
    try:
        # Теперь путь чистый (например: safety/2026/123.pdf)
        response = storage.client.get_object(bucket_name, file_path)
        pdf_bytes = response.read()
    except Exception as e:
        print(f"Ошибка MinIO: {e}") 
        raise HTTPException(status_code=500, detail=f"Ошибка чтения файла: {str(e)}")
    finally:
        if 'response' in locals():
            response.close()
            response.release_conn()
        
    # Возвращаем файл браузеру
    return Response(
        content=pdf_bytes, 
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="document_{audit_id}.pdf"'}
    )