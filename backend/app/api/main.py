from fastapi import FastAPI, Depends, HTTPException, Response, BackgroundTasks
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
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    # 1. Массово обновляем документы сотрудников
    db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id
    ).update({"status": models.DocStatus.WAITING_EMPLOYEE}, synchronize_session=False)

    # 2. Обновляем статус самой кампании
    campaign.status = models.CampaignStatus.WAITING_EMPLOYEES
    
    # 3. ДОБАВЛЯЕМ ЛОГ В AUDIT TRAIL (Чтобы HR видел это в списке)
    # Мы создаем один лог на кампанию, но фронтенд увидит переход статуса
    new_log = models.AuditTrail(
        user_id="SYSTEM_HR_DIR", # Кто подписал
        document_type=campaign.document_type,
        status=models.DocStatus.WAITING_EMPLOYEE,
        metadata_info={
            "campaign_id": campaign_id, 
            "action": "batch_signed_by_hr_director",
            "signature_id": f"sig_hr_{campaign_id}"
        }
    )
    db.add(new_log)
    
    db.commit()

    return {"status": "success", "message": f"Кампания {campaign_id} переведена в режим ожидания сотрудников"}

# # Функция, которая будет крутиться в фоне
# def send_emails_in_background(docs, campaign_id: int):
#     """
#     Эта функция запустится ПОСЛЕ того, как API ответит клиенту 200 OK.
#     Она не будет тормозить интерфейс HR-Директора.
#     """
#     for doc in docs:
#         try:
#             send_test_email(
#                 f"{doc.user_id}@company.md", 
#                 "Новый документ на подпись", 
#                 f"Перейдите в портал для подписания документа (ID: {doc.id})."
#             )
#             # В идеале здесь же можно обновлять статусы писем (доставлено/ошибка),
#             # но пока мы просто шлем в Mailpit.
#         except Exception as e:
#             print(f"Ошибка отправки email для {doc.user_id}: {e}")


# @app.post("/api/admin/campaigns/{campaign_id}/send-notifications")
# def send_campaign_notifications(campaign_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
#     """Рассылка уведомлений сотрудникам и обновление логов аудита."""
    
#     campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
#     if not campaign:
#         raise HTTPException(status_code=404, detail="Кампания не найдена")

#     docs = db.query(models.AssignedDocument).filter(
#         models.AssignedDocument.campaign_id == campaign_id,
#         models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
#     ).all()

#     # 1. МАГИЯ ФОНА: Отдаем отправку писем FastAPI. 
#     # Сервер не будет ждать их завершения!
#     background_tasks.add_task(send_emails_in_background, docs, campaign_id)

#     # 2. Мгновенно пишем логи в базу
#     for doc in docs:
#         new_log = models.AuditTrail(
#             user_id=doc.user_id,
#             document_type=campaign.document_type,
#             status=models.DocStatus.WAITING_EMPLOYEE,
#             metadata_info={"campaign_id": campaign_id, "action": "notification_sent"}
#         )
#         db.add(new_log)
    
#     db.commit()
    
#     return {"message": f"В фоне запущена рассылка {len(docs)} уведомлений. Проверьте Mailpit."}


# 1. Обновляем саму фоновую функцию (теперь она принимает список словарей)
def send_emails_in_background(docs_data: list, campaign_id: int):
    """
    Фоновая задача. Принимает список простых словарей, а не объектов БД.
    """
    for doc in docs_data:
        try:
            send_test_email(
                f"{doc['user_id']}@company.md", 
                "Новый документ на подпись", 
                f"Перейдите в портал для подписания документа (ID: {doc['id']})."
            )
        except Exception as e:
            print(f"Ошибка отправки email для {doc['user_id']}: {e}")


# 2. Обновляем эндпоинт
@app.post("/api/admin/campaigns/{campaign_id}/send-notifications")
def send_campaign_notifications(campaign_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Рассылка уведомлений сотрудникам и обновление логов аудита."""
    
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
    ).all()

    # МАГИЯ ЗДЕСЬ: Извлекаем нужные данные в обычный Python-список
    docs_data_for_background = [{"id": doc.id, "user_id": doc.user_id} for doc in docs]

    # Отдаем в фоне простой список словарей
    background_tasks.add_task(send_emails_in_background, docs_data_for_background, campaign_id)

    # Записываем логи аудита
    for doc in docs:
        new_log = models.AuditTrail(
            user_id=doc.user_id,
            document_type=campaign.document_type,
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
def get_document_pdf(user_id: str, doc_id: int, db: Session = Depends(get_db)):
    """
    Отдает PDF файл напрямую из MinIO.
    doc_id здесь — это ID из таблицы assigned_documents (или из метаданных лога).
    """
    # 1. Сначала пытаемся найти документ напрямую по ID
    doc = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.id == doc_id,
        models.AssignedDocument.user_id == user_id
    ).first()

    # 2. Если не нашли по ID (например, пришел ID лога), ищем через AuditTrail
    if not doc:
        audit_log = db.query(models.AuditTrail).filter(models.AuditTrail.id == doc_id).first()
        if audit_log and "campaign_id" in (audit_log.metadata_info or {}):
            doc = db.query(models.AssignedDocument).filter(
                models.AssignedDocument.campaign_id == audit_log.metadata_info["campaign_id"],
                models.AssignedDocument.user_id == user_id
            ).first()

    if not doc or not doc.original_pdf_path:
        raise HTTPException(status_code=404, detail="Документ или путь к PDF не найден")

    # 3. Очищаем путь от имени бакета, если он там есть
    # 'signed-documents/campaigns/6/original/file.pdf' -> 'campaigns/6/original/file.pdf'
    object_name = doc.original_pdf_path.replace("signed-documents/", "").lstrip("/")

    try:
        response = minio_client.get_object("signed-documents", object_name)
        pdf_bytes = response.read()
        response.close()
        response.release_conn()
        
        return Response(
            content=pdf_bytes, 
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"} # Чтобы открывался в браузере, а не качался
        )
    except Exception as e:
        print(f"MinIO Error: {e}")
        raise HTTPException(status_code=500, detail=f"Файл не найден в хранилище: {object_name}")

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