from fastapi import FastAPI, Depends, HTTPException, Response, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from app.services.storage import MinioService
from datetime import datetime
from typing import List
import hashlib
import smtplib
from email.message import EmailMessage

from app.celery_app import celery_app
from app.core.database import engine, get_db, SessionLocal
from app import models 
from app.models.workflow import WorkflowTemplate, WorkflowStep, SystemRole # Импорт BPM
from app.init_db import init_workflow_templates # Импорт скрипта инициализации

# Автоматическое создание всех таблиц
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Digital Doc Portal API")
storage_service = MinioService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ЗАПУСК И ИНИЦИАЛИЗАЦИЯ (Seeding BPM) ---
@app.on_event("startup")
def startup_event():
    # Запускаем скрипт создания базовых маршрутов
    db = SessionLocal()
    try:
        init_workflow_templates(db)
    finally:
        db.close()


# --- СХЕМЫ ВАЛИДАЦИИ ---
class CampaignCreateRequest(BaseModel):
    title: str
    template_id: int = None      # Опционально, если выбран готовый
    custom_steps: List[str] = None # Список ролей для кастомного маршрута
    employee_ids: List[str]
    document_type: str = "standard_doc"

class SignRequest(BaseModel):
    user_id: str
    role: str  # hr_director, employee, sys_admin, it_director


# --- ИНТЕГРАЦИЯ С MAILPIT ---
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
        print(f"Ошибка отправки почты: {e}")

def send_emails_in_background(docs_data: list, campaign_id: int):
    for doc in docs_data:
        try:
            send_test_email(
                f"{doc['user_id']}@company.md", 
                "Новый документ на подпись", 
                f"Перейдите в портал для подписания документа (ID: {doc['id']})."
            )
        except Exception as e:
            print(f"Ошибка отправки email для {doc['user_id']}: {e}")


# ==========================================
# НОВЫЙ ДВИЖОК МАРШРУТОВ (УНИВЕРСАЛЬНЫЙ BPM)
# ==========================================

@app.get("/api/bpm/inbox")
def get_universal_inbox(role: str, user_id: str = None, db: Session = Depends(get_db)):
    """
    Умный Инбокс. Возвращает документы, которые СЕЙЧАС ждут подписи этой роли.
    Если роль 'employee', то показывает только его личные документы.
    Если роль 'sys_admin', показывает все документы по компании, ждущие админа.
    """
    # Делаем JOIN документа с таблицей шагов по текущему индексу
    query = db.query(models.AssignedDocument, models.WorkflowStep).join(
        models.WorkflowStep,
        (models.AssignedDocument.workflow_template_id == models.WorkflowStep.template_id) &
        (models.AssignedDocument.current_step_order == models.WorkflowStep.step_order)
    ).filter(
        models.WorkflowStep.role_required == role,
        models.AssignedDocument.status != "FULLY_SIGNED" # Не берем завершенные
    )

    if role == SystemRole.EMPLOYEE.value and user_id:
        query = query.filter(models.AssignedDocument.user_id == user_id)

    results = query.all()
    
    inbox = []
    for doc, step in results:
        inbox.append({
            "doc_id": doc.id,
            "campaign_id": doc.campaign_id,
            "user_id": doc.user_id,
            "workflow_step": step.step_order,
            "is_final_step": step.is_final,
            "created_at": doc.created_at.strftime("%d.%m.%Y")
        })
    return inbox


@app.post("/api/bpm/documents/{doc_id}/sign")
def universal_sign_document(doc_id: int, req: SignRequest, db: Session = Depends(get_db)):
    """Универсальная подпись. Подходит для ЛЮБОГО шага и ЛЮБОЙ роли."""
    doc = db.query(models.AssignedDocument).filter(models.AssignedDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    # 1. Ищем текущий шаг
    step = db.query(models.WorkflowStep).filter(
        models.WorkflowStep.template_id == doc.workflow_template_id,
        models.WorkflowStep.step_order == doc.current_step_order
    ).first()

    if not step:
        raise HTTPException(status_code=400, detail="Маршрут завершен или сломан")

    # 2. Проверяем, имеет ли право эта роль сейчас подписывать
    if step.role_required != req.role:
        raise HTTPException(status_code=403, detail=f"Сейчас очередь роли {step.role_required}, а вы {req.role}")
    
    if req.role == SystemRole.EMPLOYEE.value and doc.user_id != req.user_id:
        raise HTTPException(status_code=403, detail="Нельзя подписать чужой документ")

    # 3. Пишем лог подписи
    new_log = models.AuditTrail(
        user_id=req.user_id,
        document_type=doc.campaign.document_type if doc.campaign else "bpm_doc",
        status=f"SIGNED_STEP_{doc.current_step_order}",
        metadata_info={"action": f"signed_by_{req.role}", "step": doc.current_step_order}
    )
    db.add(new_log)

    # 4. Двигаем документ по маршруту
    if step.is_final:
        doc.status = "FULLY_SIGNED"
    else:
        doc.current_step_order += 1
        doc.status = "IN_PROGRESS"

    db.commit()
    return {"status": "success", "message": "Подписано!", "is_final": step.is_final, "next_step": doc.current_step_order}


# ==========================================
# СТАРЫЕ ЭНДПОИНТЫ (Адаптированные под BPM)
# ==========================================

@app.post("/api/admin/campaigns/create")
def create_campaign(request: CampaignCreateRequest, db: Session = Depends(get_db)):
    try:
        # 1. ОПРЕДЕЛЯЕМ МАРШРУТ
        target_template_id = None

        if request.custom_steps:
            # СОЗДАЕМ КАСТОМНЫЙ ШАБЛОН НА ЛЕТУ
            new_template = models.WorkflowTemplate(
                name=f"Custom: {request.title} ({datetime.now().strftime('%d.%m %H:%M')})",
                document_type=request.document_type
            )
            db.add(new_template)
            db.flush() # Получаем ID шаблона
            
            # Нарезаем шаги из присланного массива ролей
            for idx, role in enumerate(request.custom_steps):
                new_step = models.WorkflowStep(
                    template_id=new_template.id,
                    step_order=idx + 1,
                    role_required=role,
                    is_final=(idx == len(request.custom_steps) - 1)
                )
                db.add(new_step)
            
            target_template_id = new_template.id
        else:
            # Берем существующий ID
            target_template_id = request.template_id

        if not target_template_id:
            raise HTTPException(status_code=400, detail="Не указан маршрут")

        # 2. СОЗДАЕМ КАМПАНИЮ И ДОКУМЕНТЫ (как раньше)
        new_campaign = models.DocumentCampaign(
            title=request.title,
            created_by_hr_id="SYSTEM_HR",
            hr_director_id="SYSTEM_HR_DIR",
            document_type=request.document_type,
            status=models.CampaignStatus.GENERATING_PDFS
        )
        db.add(new_campaign)
        db.flush()

        for emp_id in request.employee_ids:
            new_doc = models.AssignedDocument(
                campaign_id=new_campaign.id,
                user_id=emp_id,
                workflow_template_id=target_template_id,
                current_step_order=1,
                status="DRAFT"
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

            celery_app.send_task(
                "app.worker.generate_document_task", 
                args=[new_doc.id, new_doc.user_id, request.document_type]
            )

        return {"status": "success", "template_id": target_template_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/campaigns/{campaign_id}/sign-by-hr")
def sign_campaign_by_hr(campaign_id: int, db: Session = Depends(get_db)):
    """Слегка обновленная подпись HR (эмулируем прохождение Шага 1)"""
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    
    # 1. Двигаем документы на следующий шаг
    docs = db.query(models.AssignedDocument).filter(models.AssignedDocument.campaign_id == campaign_id).all()
    for doc in docs:
        doc.status = models.DocStatus.WAITING_EMPLOYEE
        doc.current_step_order = 2 # Переводим на Шаг 2 (Сотрудник)
    
    campaign.status = models.CampaignStatus.WAITING_EMPLOYEES
    
    new_log = models.AuditTrail(
        user_id="SYSTEM_HR_DIR", 
        document_type=campaign.document_type,
        status=models.DocStatus.WAITING_EMPLOYEE,
        metadata_info={"campaign_id": campaign_id, "action": "batch_signed_by_hr_director"}
    )
    db.add(new_log)
    db.commit()

    return {"status": "success"}

# --- ОСТАЛЬНЫЕ ЭНДПОИНТЫ (Без изменений) ---
# ... (Тут остаются твои get_all_audit_logs, send_campaign_notifications, get_document_pdf, get_admin_stats и html-роуты) ...

@app.get("/api/documents/all")
def get_all_audit_logs(db: Session = Depends(get_db)):
    return db.query(models.AuditTrail).order_by(models.AuditTrail.id.desc()).all()

@app.post("/api/admin/campaigns/{campaign_id}/send-notifications")
def send_campaign_notifications(campaign_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    campaign = db.query(models.DocumentCampaign).filter(models.DocumentCampaign.id == campaign_id).first()
    docs = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.campaign_id == campaign_id,
        models.AssignedDocument.status == models.DocStatus.WAITING_EMPLOYEE
    ).all()
    docs_data_for_background = [{"id": doc.id, "user_id": doc.user_id} for doc in docs]
    background_tasks.add_task(send_emails_in_background, docs_data_for_background, campaign_id)
    db.commit()
    return {"message": "Уведомления отправлены"}

@app.get("/api/documents/{user_id}/{doc_id}/pdf")
def get_document_pdf(user_id: str, doc_id: int, db: Session = Depends(get_db)):
    """Отдает PDF файл напрямую из MinIO через сервис."""
    
    # 1. Пытаемся найти документ напрямую по ID
    doc = db.query(models.AssignedDocument).filter(
        models.AssignedDocument.id == doc_id,
        models.AssignedDocument.user_id == user_id
    ).first()

    # 2. Если фронтенд прислал нам ID из логов (AuditTrail), ищем через кампанию
    if not doc:
        audit_log = db.query(models.AuditTrail).filter(models.AuditTrail.id == doc_id).first()
        if audit_log and audit_log.metadata_info and "campaign_id" in audit_log.metadata_info:
            doc = db.query(models.AssignedDocument).filter(
                models.AssignedDocument.campaign_id == audit_log.metadata_info["campaign_id"],
                models.AssignedDocument.user_id == user_id
            ).first()

    if not doc or not doc.original_pdf_path:
        raise HTTPException(status_code=404, detail="Документ еще генерируется или не найден")

    # Очищаем путь: 'signed-documents/campaigns/6/original/file.pdf' -> 'campaigns/6/original/file.pdf'
    object_name = doc.original_pdf_path.replace("signed-documents/", "").lstrip("/")

    # 3. Достаем файл через наш сервис
    try:
        # Вся магия с коннектами теперь спрятана внутри storage_service
        pdf_bytes = storage_service.get_pdf(object_name)
        
        return Response(
            content=pdf_bytes, 
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"} 
        )
    except Exception as e:
        print(f"Ошибка сервиса хранилища: {e}")
        raise HTTPException(status_code=500, detail="Ошибка загрузки файла из хранилища")
    
@app.get("/api/bpm/templates")
def get_workflow_templates(db: Session = Depends(get_db)):
    """Отдает список всех доступных маршрутов для выпадающего списка HR"""
    templates = db.query(WorkflowTemplate).all()
    return [{"id": t.id, "name": t.name, "doc_type": t.document_type} for t in templates]

@app.get("/hr")
def page_hr(): return FileResponse("templates/hr_dashboard.html")

@app.get("/director/hr")
def page_hr_director(): return FileResponse("templates/hr_director.html")

@app.get("/cabinet")
def page_employee_cabinet(): return FileResponse("templates/employee_cabinet.html")

@app.get("/director/it")
def page_it_director(): return FileResponse("templates/it_director.html")