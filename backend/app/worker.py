import asyncio
import hashlib
import os
from io import BytesIO
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app import models

from app.services.storage import MinioService 

async def render_pdf_with_playwright(audit_id: int, user_id: str, doc_type: str) -> bytes:
    """Генерация PDF с динамическим выбором контента"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "templates")
    env = Environment(loader=FileSystemLoader(template_path))
    
    template_name = f"{doc_type}.html"
    if not os.path.exists(os.path.join(template_path, template_name)):
        template_name = "doc_template.html" 
    
    template = env.get_template(template_name)
    
    titles = {
        "safety_instruction_2026": "ВВОДНЫЙ ИНСТРУКТАЖ ПО ТЕХНИКЕ БЕЗОПАСНОСТИ",
        "nda_2026": "СОГЛАШЕНИЕ О НЕРАЗГЛАШЕНИИ (NDA)",
        "remote_work_policy": "ПОЛИТИКА УДАЛЕННОЙ РАБОТЫ"
    }

    doc_texts = {
        "safety_instruction_2026": """
            1. Общие положения по охране труда. <br>
            2. Сотрудник обязан соблюдать правила внутреннего распорядка. <br>
            3. При возникновении ЧС немедленно сообщить руководству.
        """,
        "nda_2026": """
            1. Предмет соглашения. <br>
            Стороны договорились о неразглашении конфиденциальной информации, полученной в ходе работы.<br><br>
            2. Обязанности сотрудника. <br>
            Сотрудник обязуется не передавать третьим лицам исходный код, клиентские базы и финансовые данные компании.
        """,
        "remote_work_policy": """
            1. Рабочие часы с 9:00 до 18:00 по местному времени.<br>
            2. Сотрудник обязан быть на связи в корпоративном мессенджере.<br>
            3. Использование VPN при подключении к рабочим серверам обязательно.
        """
    }

    current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    current_content = doc_texts.get(doc_type, "Текст документа не найден в системе.")
    
    html_content = template.render(
        title=titles.get(doc_type, "ОФИЦИАЛЬНЫЙ ДОКУМЕНТ"),
        document_content=current_content,
        audit_id=audit_id,
        user_id=user_id,
        sign_date=current_date,
        doc_hash=hashlib.md5(str(audit_id).encode()).hexdigest()[:10] 
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_content(html_content)
        await page.wait_for_load_state("networkidle")
        pdf_bytes = await page.pdf(
            format="A4", 
            print_background=True,
            margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"}
        )
        await browser.close()
        return pdf_bytes

@celery_app.task(name="app.worker.generate_document_task")
def generate_document_task(doc_id: int, user_id: str, doc_type: str):
    db: Session = SessionLocal()
    
    try:
        doc_record = db.query(models.AssignedDocument).filter(models.AssignedDocument.id == doc_id).first()
        if not doc_record:
            return {"status": "error", "message": "Record not found"}

        # ИСПОЛЬЗУЕМ НАШУ УМНУЮ ФУНКЦИЮ!
        pdf_bytes = asyncio.run(render_pdf_with_playwright(doc_id, user_id, doc_type))
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        
        campaign_id = doc_record.campaign_id
        file_name = f"campaigns/{campaign_id}/original/{user_id}_{doc_type}.pdf"
        
        minio_service = MinioService()
        storage_path = minio_service.upload_pdf(file_name=file_name, pdf_bytes=pdf_bytes)
        
        doc_record.original_pdf_path = storage_path
        doc_record.status = models.DocStatus.DRAFT  
        doc_record.updated_at = datetime.now(timezone.utc)
        
        audit_log = models.AuditTrail(
            user_id=user_id,
            document_type=doc_type,
            status=models.DocStatus.DRAFT, 
            metadata_info={
                "action": "pdf_generated", 
                "file_path": storage_path,
                "sha256_hash": file_hash,
                "campaign_id": campaign_id
            }
        )
        db.add(audit_log)
        db.commit()
        
        return {"status": "success", "file": storage_path, "doc_id": doc_id}
        
    except Exception as e:
        db.rollback()
        doc_record = db.query(models.AssignedDocument).filter(models.AssignedDocument.id == doc_id).first()
        if doc_record:
            doc_record.status = models.DocStatus.ERROR
            db.commit()
        print(f"Ошибка в воркере: {e}") 
        raise e
    finally:
        db.close()