from urllib import request

from fastapi import FastAPI, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from datetime import datetime
from app.celery_app import celery_app
from sqlalchemy import func
from typing import List
import hashlib
from io import BytesIO

# Импортируем нашу базу и ВСЕ модели через __init__.py
from app.core.database import engine, get_db
from app import models 


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

class CampaignCreateRequest(BaseModel):
    title: str
    document_type: str
    hr_director_id: str
    employee_ids: List[str]

# --- РОУТЫ ДЛЯ СОТРУДНИКА ---

@app.get("/api/documents/{user_id}/list")
def get_user_documents(user_id: str, db: Session = Depends(get_db)):
    """Показывает сотруднику документы, только если HR-Директор их УЖЕ подписал пакетно"""
        
    assignments = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.user_id == user_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE # Фильтр по статусу!
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
            models.AuditTrail.document_type == assign.campaign.document_type
        ).order_by(models.AuditTrail.id.desc()).first()

        status = record.status if record else assign.status
        
        result.append({
            "id": assign.campaign.document_type,
            "title": titles.get(assign.campaign.document_type, "Документ без названия"),
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
    for doc in new_docs:
        celery_app.send_task(
            "app.worker.generate_document_task", 
            args=[doc.id, doc.user_id, request.document_type]
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

@app.post("/api/admin/campaigns/create")
def create_campaign(request: CampaignCreateRequest, db: Session = Depends(get_db)):
    """
    1. Создается кампания.
    2. Создаются документы (получаем их ID).
    3. Запускается Celery с корректными doc_id.
    """
    try:
        # 1. Создаем родительскую кампанию
        new_campaign = models.DocumentCampaign(
            title=request.title,
            document_type=request.document_type,
            created_by_hr_id="hr_specialist_1", 
            hr_director_id=request.hr_director_id,
            status=models.CampaignStatus.GENERATING_PDFS
        )
        db.add(new_campaign)
        db.flush() # Получаем ID кампании без полного коммита

        # 2. Создаем документы по одному, чтобы получить их ID для Celery
        for emp_id in request.employee_ids:
            new_doc = models.AssignedDocument(
                campaign_id=new_campaign.id,
                user_id=emp_id,
                status=models.DocStatus.DRAFT
            )
            db.add(new_doc)
            db.commit() # <--- ТЕПЕРЬ ТУТ! Запись зафиксирована.
            db.refresh(new_doc) # Получаем актуальный ID

            celery_app.send_task(
                "app.worker.generate_document_task", 
                args=[new_doc.id, new_doc.user_id, request.document_type]
            )

        # 4. Только теперь делаем финальный коммит всех записей
        # db.commit()

        return {
            "status": "success", 
            "campaign_id": new_campaign.id, 
            "count": len(request.employee_ids)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при создании кампании: {str(e)}")

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


@app.get("/api/admin/campaigns/{campaign_id}/prepare-signature")
def prepare_campaign_signature(campaign_id: int, db: Session = Depends(get_db)):
    """
    Собирает все документы кампании для подписи HR-директора.
    Возвращает список хешей и путей к файлам.
    """
    # 1. Берем все документы этой кампании, где PDF уже сгенерирован
    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.original_pdf_path != None
    ).all()

    if not docs:
        raise HTTPException(status_code=404, detail="Нет готовых PDF для этой кампании")

    documents_to_sign = []
    
    for doc in docs:
        try:
            # Получаем файл из MinIO для проверки и хеширования
            response = minio_client.get_object("signed-documents", doc.original_pdf_path)
            content = response.read()
            response.close()
            response.release_conn()

            # Вычисляем SHA-256 хеш (именно его ждет MSign)
            file_hash = hashlib.sha256(content).hexdigest()

            documents_to_sign.append({
                "doc_id": doc.id,
                "user_id": doc.user_id,
                "file_path": doc.original_pdf_path,
                "hash": file_hash,
                "title": f"Документ для {doc.user_id}"
            })
        except Exception as e:
            # Если файл потерялся в MinIO, помечаем ошибку
            continue

    return {
        "campaign_id": campaign_id,
        "count": len(documents_to_sign),
        "documents": documents_to_sign
    }

# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ MSIGN MOCK И WORKFLOW ---

@app.post("/api/admin/campaigns/{campaign_id}/sign-by-hr")
def sign_campaign_by_hr(campaign_id: int, db: Session = Depends(get_db)):
    """
    Имитация подписи HR-директора через MSign.
    После этого шага документы становятся видимы сотрудникам.
    """
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    # 1. Имитируем запрос к MSign (Заглушка)
    # В реальности здесь был бы запрос к внешнему API
    msign_mock_response = {
        "status": "SUCCESS",
        "signature_id": f"sig_hr_{campaign_id}_{datetime.now().timestamp()}",
        "signed_at": datetime.now().isoformat()
    }

    # 2. Обновляем статус кампании
    campaign.status = models.CampaignStatus.WAITING_EMPLOYEES
    
    # 3. Самое важное: переводим все документы из DRAFT в WAITING_EMPLOYEE
    # Теперь сотрудники увидят их в своих личных кабинетах (/api/documents/{user_id}/list)
    db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id
    ).update({"status": models.DocStatus.WAITING_EMPLOYEE})

    db.commit()

    return {
        "message": f"Кампания {campaign_id} успешно подписана HR-директором",
        "msign_data": msign_mock_response
    }


@app.post("/api/documents/{doc_id}/employee-sign")
def employee_sign_document(doc_id: int, db: Session = Depends(get_db)):
    """
    Имитация подписи конкретного документа сотрудником.
    """
    doc = db.query(models.AssignedDocument).filter(models.AssignedDocument.id == doc_id).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    if doc.status != models.DocStatus.WAITING_EMPLOYEE:
        raise HTTPException(status_code=400, detail="Документ не готов к подписи сотрудником")

    # 1. Имитируем подпись (MSign Mock)
    doc.status = models.DocStatus.SIGNED
    
    # 2. Логируем в AuditTrail (чтобы HR видел историю)
    new_log = models.AuditTrail(
        user_id=doc.user_id,
        document_type="safety_instruction_2026", # В будущем брать из кампании
        status="DOCUMENT_SIGNED_PEP",
        metadata_info={"signed_at": datetime.now().isoformat(), "doc_id": doc_id}
    )
    db.add(new_log)
    db.commit()

    return {"status": "success", "message": f"Документ {doc_id} подписан сотрудником"}


@app.post("/api/admin/campaigns/{campaign_id}/send-notifications")
def send_campaign_notifications(campaign_id: int, db: Session = Depends(get_db)):
    """
    Рассылка уведомлений сотрудникам через Celery.
    Письма полетят в Mailpit.
    """
    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
    ).all()

    # В будущем здесь будет вызов Celery задачи:
    # celery_app.send_task("app.worker.send_email_task", args=[...])
    
    return {
        "message": f"Запущена рассылка {len(docs)} уведомлений. Проверьте Mailpit (порт 8025)"
    }

