from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from datetime import datetime
from typing import List
import hashlib
import smtplib
from email.message import EmailMessage
from uuid import uuid4  # Исправлено: Добавлен импорт для мока MSign

from app.celery_app import celery_app
from app.core.database import engine, get_db
from app import models 

# Автоматическое создание всех таблиц
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

class CampaignCreateRequest(BaseModel):
    title: str
    document_type: str
    hr_director_id: str
    employee_ids: List[str]

class AssignRequest(BaseModel):
    user_id: str
    document_type: str


# --- ИНТЕГРАЦИЯ С MAILPIT (Вспомогательная функция) ---
def send_test_email(to_email: str, subject: str, content: str):
    msg = EmailMessage()
    msg.set_content(content)
    msg["Subject"] = subject
    msg["From"] = "portal@company.md"
    msg["To"] = to_email

    try:
        with smtplib.SMTP("mailpit", 1025) as s:
            s.send_message(msg)
    except Exception as e:
        print(f"Ошибка отправки почты (Mailpit может быть выключен): {e}")


# --- РОУТЫ ДЛЯ СОТРУДНИКА ---

@app.get("/api/documents/{user_id}/list")
def get_user_documents(user_id: str, db: Session = Depends(get_db)):
    """Показывает сотруднику документы, только если HR-Директор их УЖЕ подписал пакетно"""
    assignments = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.user_id == user_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
    ).all()
    
    titles = {
        "safety_instruction_2026": "Вводный инструктаж по ТБ (2026)",
        "nda_2026": "Соглашение о неразглашении (NDA)",
        "remote_work_policy": "Политика удаленной работы"
    }

    result = []
    for assign in assignments:
        doc_type = assign.campaign.document_type if assign.campaign else "unknown"
        
        record = db.query(models.AuditTrail).filter(
            models.AuditTrail.user_id == user_id,
            models.AuditTrail.document_type == doc_type
        ).order_by(models.AuditTrail.id.desc()).first()

        status = record.status if record else assign.status
        
        result.append({
            "id": doc_type,
            "title": titles.get(doc_type, "Документ без названия"),
            "date": assign.created_at.strftime("%d.%m.%Y"),
            "status": status,
            "doc_id": assign.id
        })
        
    return result


@app.post("/api/documents/{doc_id}/employee-sign")
def employee_sign_document(doc_id: int, db: Session = Depends(get_db)):
    """Подписание документа сотрудником (ПЭП/MSign)"""
    
    # 1. Фронтенд присылает ID из таблицы AuditTrail (например, 47).
    # Ищем этот лог, чтобы вытащить campaign_id и user_id.
    audit_log = db.query(models.AuditTrail).filter(models.AuditTrail.id == doc_id).first()
    
    doc = None
    if audit_log and audit_log.metadata_info and "campaign_id" in audit_log.metadata_info:
        # Ура, лог найден! Ищем реальный документ по кампании и юзеру
        campaign_id = audit_log.metadata_info["campaign_id"]
        user_id = audit_log.user_id
        
        doc = db.query(models.AssignedDocument).filter(
            models.AssignedDocument.campaign_id == campaign_id,
            models.AssignedDocument.user_id == user_id
        ).first()
    else:
        # Резервный вариант: вдруг нам когда-нибудь пришлют реальный ID документа
        doc = db.query(models.AssignedDocument).filter(models.AssignedDocument.id == doc_id).first()

    # Если ничего не нашли — выдаем ту самую ошибку
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    # 2. МЕНЯЕМ СТАТУС ДОКУМЕНТА НА ПОДПИСАН
    doc.status = models.DocStatus.FULLY_SIGNED
    
    # 3. ПИШЕМ НОВЫЙ ЛОГ, чтобы фронтенд сразу увидел зеленую галочку
    new_log = models.AuditTrail(
        user_id=doc.user_id,
        document_type=audit_log.document_type if audit_log else "unknown",
        status=models.DocStatus.FULLY_SIGNED,
        metadata_info={"campaign_id": doc.campaign_id, "action": "signed_by_employee"}
    )
    db.add(new_log)
    
    # 4. Сохраняем всё в базу
    db.commit()
    
    return {"message": "Документ успешно подписан"}

# --- РОУТЫ ДЛЯ HR (АДМИН) ---

@app.get("/api/documents/all")
def get_all_audit_logs(db: Session = Depends(get_db)):
    """История всех действий для HR-панели"""
    return db.query(models.AuditTrail).order_by(models.AuditTrail.id.desc()).all()


@app.post("/api/admin/campaigns/create")
def create_campaign(request: CampaignCreateRequest, db: Session = Depends(get_db)):
    """Создает кампанию и запускает генерацию PDF в фоне"""
    try:
        new_campaign = models.DocumentCampaign(
            title=request.title,
            document_type=request.document_type,
            created_by_hr_id="hr_specialist_1", 
            hr_director_id=request.hr_director_id,
            status=models.CampaignStatus.GENERATING_PDFS
        )
        db.add(new_campaign)
        db.flush()

        for emp_id in request.employee_ids:
            new_doc = models.AssignedDocument(
                campaign_id=new_campaign.id,
                user_id=emp_id,
                status=models.DocStatus.DRAFT
            )
            db.add(new_doc)
            db.commit() # Фиксируем для воркера
            db.refresh(new_doc)

            celery_app.send_task(
                "app.worker.generate_document_task", 
                args=[new_doc.id, new_doc.user_id, request.document_type]
            )

        return {
            "status": "success", 
            "campaign_id": new_campaign.id, 
            "count": len(request.employee_ids)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при создании кампании: {str(e)}")


@app.post("/api/admin/campaigns/{campaign_id}/sign-by-hr")
def sign_campaign_by_hr(campaign_id: int, db: Session = Depends(get_db)):
    """Имитация подписи HR-директора через MSign."""
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    msign_mock_response = {
        "status": "SUCCESS",
        "signature_id": f"sig_hr_{campaign_id}_{datetime.now().timestamp()}",
        "signed_at": datetime.now().isoformat()
    }

    campaign.status = models.CampaignStatus.WAITING_EMPLOYEES
    
    # Исправлено: добавлен synchronize_session=False для надежности
    db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id
    ).update({"status": models.DocStatus.WAITING_EMPLOYEE}, synchronize_session=False)

    db.commit()

    return {
        "message": f"Кампания {campaign_id} успешно подписана HR-директором",
        "msign_data": msign_mock_response
    }

@app.post("/api/admin/campaigns/{campaign_id}/send-notifications")
def send_campaign_notifications(campaign_id: int, db: Session = Depends(get_db)):
    """Рассылка уведомлений сотрудникам и обновление логов аудита."""
    
    # 1. Используем ПРАВИЛЬНОЕ имя модели: DocumentCampaign
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
        
    doc_type = campaign.document_type 

    # 2. Находим документы (используем AssignedDocument)
    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
    ).all()

    for doc in docs:
        # Отправка письма в Mailpit
        send_test_email(
            f"{doc.user_id}@company.md", 
            "Новый документ на подпись", 
            f"Перейдите в портал для подписания документа (ID: {doc.id})."
        )
        
        # 3. Пишем лог аудита, чтобы фронтенд увидел обновление
        new_log = models.AuditTrail(
            user_id=doc.user_id,
            document_type=doc_type,
            status=models.DocStatus.WAITING_EMPLOYEE,
            metadata_info={"campaign_id": campaign_id, "action": "notification_sent"}
        )
        db.add(new_log)
    
    db.commit()
    
    return {"message": f"В очередь добавлено {len(docs)} уведомлений. Проверьте Mailpit (порт 8025)"}

# --- РАБОТА С PDF (MinIO) И СТАТИСТИКА ---

minio_client = Minio(
    "minio:9000",
    access_key="admin",
    secret_key="password123",
    secure=False
)

@app.get("/api/admin/campaigns/{campaign_id}/prepare-signature")
def prepare_campaign_signature(campaign_id: int, db: Session = Depends(get_db)):
    """Собирает хеши документов кампании для подписи."""
    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.original_pdf_path != None
    ).all()

    if not docs:
        raise HTTPException(status_code=404, detail="Нет готовых PDF для этой кампании")

    documents_to_sign = []
    for doc in docs:
        try:
            response = minio_client.get_object("signed-documents", doc.original_pdf_path)
            content = response.read()
            response.close()
            response.release_conn()

            file_hash = hashlib.sha256(content).hexdigest()
            documents_to_sign.append({
                "doc_id": doc.id,
                "user_id": doc.user_id,
                "file_path": doc.original_pdf_path,
                "hash": file_hash,
                "title": f"Документ для {doc.user_id}"
            })
        except Exception:
            continue

    return {
        "campaign_id": campaign_id,
        "count": len(documents_to_sign),
        "documents": documents_to_sign
    }

@app.get("/api/documents/{user_id}/{doc_id}/pdf")
def get_document_pdf(user_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(models.AuditTrail).filter(
        models.AuditTrail.user_id == user_id,
        models.AuditTrail.document_type == doc_id
    ).order_by(models.AuditTrail.id.desc()).first()
    
    if not doc or doc.status != models.DocStatus.FULLY_SIGNED:
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
    total_employees = db.query(models.AssignedDocument.user_id).distinct().count()
    signed_count = db.query(models.AuditTrail).filter(models.AuditTrail.status == models.DocStatus.FULLY_SIGNED).count()
    total_assignments = db.query(models.AssignedDocument).count()
    pending_count = total_assignments - signed_count if total_assignments > signed_count else 0

    return {
        "total_employees": total_employees,
        "signed_today": signed_count,
        "awaiting_signature": pending_count
    }

@app.get("/hr")
def page_hr():
    return FileResponse("templates/hr_dashboard.html")

@app.get("/director/hr")
def page_hr_director():
    return FileResponse("templates/hr_director.html")

@app.get("/cabinet")
def page_employee_cabinet():
    return FileResponse("templates/employee_cabinet.html")

# Заделы на будущее:
@app.get("/director/it")
def page_it_director():
    return FileResponse("templates/it_director.html")

@app.get("/account")
def page_accounting():
    return FileResponse("templates/accounting.html")