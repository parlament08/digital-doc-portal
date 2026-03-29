from fastapi import FastAPI, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from datetime import datetime
from app.celery_app import celery_app
from sqlalchemy import func

# Импортируем нашу базу и ВСЕ модели через __init__.py
from app.core.database import engine, get_db
from app import models 
from app.worker import generate_document_task

# Автоматическое создание всех таблиц (AuditTrail и AssignedDocument)
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Digital Doc Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- СХЕМЫ ВАЛИДАЦИИ (Pydantic) ---

class SignRequest(BaseModel):
    user_id: str
    document_type: str

class AssignRequest(BaseModel):
    user_id: str
    document_type: str

# --- РОУТЫ ДЛЯ СОТРУДНИКА ---

@app.get("/api/documents/{user_id}/list")
def get_user_documents(user_id: str, db: Session = Depends(get_db)):
    """Показывает сотруднику только те документы, которые ему назначил HR"""
    
    # 1. Получаем список всех назначений для юзера
    assignments = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.user_id == user_id
    ).all()
    
    # Справочник названий (в будущем будет в отдельной таблице БД)
    titles = {
        "safety_instruction_2026": "Вводный инструктаж по ТБ (2026)",
        "nda_2026": "Соглашение о неразглашении (NDA)",
        "remote_work_policy": "Политика удаленной работы"
    }

    result = []
    for assign in assignments:
        # 2. Для каждого назначения ищем самую свежую запись о подписании
        record = db.query(models.AuditTrail).filter(
            models.AuditTrail.user_id == user_id,
            models.AuditTrail.document_type == assign.document_type
        ).order_by(models.AuditTrail.id.desc()).first()

        status = record.status if record else assign.status
        
        result.append({
            "id": assign.document_type,
            "title": titles.get(assign.document_type, "Документ без названия"),
            "date": assign.created_at.strftime("%d.%m.%Y"),
            "status": status
        })
        
    return result

@app.post("/api/sign")
def sign_document(request: SignRequest, db: Session = Depends(get_db)):
    """Запуск процесса подписания"""
    audit_record = models.AuditTrail(
        user_id=request.user_id,
        document_type=request.document_type,
        status="GENERATION_IN_PROGRESS"
    )
    db.add(audit_record)
    db.commit()
    db.refresh(audit_record)

    # 2. Отправляем задачу воркеру ПО ИМЕНИ (как в декораторе воркера)
    celery_app.send_task(
        "app.worker.generate_document_task", 
        args=[audit_record.id, request.user_id, request.document_type]
    )

    # generate_document_task.delay(
    #     audit_id=audit_record.id, 
    #     user_id=request.user_id, 
    #     doc_type=request.document_type
    # )

    return {"message": "Процесс запущен", "audit_id": audit_record.id}

# --- РОУТЫ ДЛЯ HR (АДМИН) ---

@app.get("/api/documents/all")
def get_all_audit_logs(db: Session = Depends(get_db)):
    """История всех действий для HR-панели"""
    logs = db.query(models.AuditTrail).order_by(models.AuditTrail.id.desc()).all()
    return logs

@app.post("/api/admin/assign")
def assign_document(request: AssignRequest, db: Session = Depends(get_db)):
    """HR назначает новый документ сотруднику"""
    # Проверяем, не назначен ли уже такой документ
    exists = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.user_id == request.user_id,
        models.AssignedDocument.document_type == request.document_type
    ).first()
    
    if exists:
        return {"message": "Документ уже был назначен ранее"}

    new_assign = models.AssignedDocument(
        user_id=request.user_id,
        document_type=request.document_type,
        status="PENDING"
    )
    db.add(new_assign)
    db.commit()
    return {"message": f"Документ {request.document_type} назначен пользователю {request.user_id}"}

# --- РАБОТА С PDF (MinIO) ---

minio_client = Minio(
    "minio:9000",
    access_key="admin",
    secret_key="password123",
    secure=False
)

@app.get("/api/documents/{user_id}/{doc_id}/pdf")
def get_document_pdf(user_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(models.AuditTrail).filter(
        models.AuditTrail.user_id == user_id,
        models.AuditTrail.document_type == doc_id
    ).order_by(models.AuditTrail.id.desc()).first()
    
    if not doc or doc.status != "DOCUMENT_SIGNED_PEP":
        raise HTTPException(status_code=404, detail="PDF не найден")
    
    metadata = doc.metadata_info or {}
    file_path = metadata.get("file_path")
    
    if file_path:
        object_name = file_path.replace("signed-documents/", "")
    else:
        year = doc.created_at.year if doc.created_at else 2026
        object_name = f"{doc.document_type}/{year}/{doc.id}_{doc.document_type}_{doc.user_id}.pdf"
    
    try:
        response = minio_client.get_object("signed-documents", object_name)
        pdf_bytes = response.read()
        response.close()
        response.release_conn()
        return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка MinIO: {str(e)}")
    

@app.get("/api/admin/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    # 1. Считаем общее кол-во уникальных сотрудников, которым что-то назначено
    total_employees = db.query(models.AssignedDocument.user_id).distinct().count()
    
    # 2. Считаем, сколько документов РЕАЛЬНО подписано (есть в аудите со статусом SUCCESS)
    signed_count = db.query(models.AuditTrail).filter(
        models.AuditTrail.status == "DOCUMENT_SIGNED_PEP"
    ).count()
    
    # 3. Считаем, сколько документов еще ждут подписи
    # (Всего назначений минус уже подписанные)
    total_assignments = db.query(models.AssignedDocument).count()
    pending_count = total_assignments - signed_count if total_assignments > signed_count else 0

    return {
        "total_employees": total_employees,
        "signed_today": signed_count, # Для MVP считаем все подписанные
        "awaiting_signature": pending_count
    }

