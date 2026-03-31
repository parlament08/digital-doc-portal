import asyncio
import hashlib
import os
from io import BytesIO
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from minio import Minio
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app import models  # Важно: импортируем весь пакет моделей

# Настройки MinIO
MINIO_URL = os.environ.get("MINIO_URL", "minio:9000")
MINIO_USER = os.environ.get("MINIO_ROOT_USER", "admin")
MINIO_PASS = os.environ.get("MINIO_ROOT_PASSWORD", "password123")
BUCKET_NAME = "signed-documents"

def get_minio_client():
    client = Minio(MINIO_URL, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=False)
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)
    return client

async def render_pdf_with_playwright(audit_id: int, user_id: str, doc_type: str) -> bytes:
    """Генерация PDF с динамическим выбором контента"""
    
    # Определяем путь к папке шаблонов относительно текущего файла
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "templates")
    
    env = Environment(loader=FileSystemLoader(template_path))
    
    # Пытаемся найти специфичный шаблон или используем базовый корпоративный
    template_name = f"{doc_type}.html"
    if not os.path.exists(f"app/templates/{template_name}"):
        template_name = "doc_template.html" # Наш универсальный шаблон со штампом
    
    template = env.get_template(template_name)
    
    # Справочник названий для заголовка внутри PDF
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

    # 2. Данные для рендеринга (теперь со штампом)
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    current_content = doc_texts.get(doc_type, "Текст документа не найден в системе.")
    
    html_content = template.render(
        title=titles.get(doc_type, "ОФИЦИАЛЬНЫЙ ДОКУМЕНТ"),
        document_content=current_content,
        audit_id=audit_id,
        user_id=user_id,
        sign_date=current_date,
        doc_hash=hashlib.md5(str(audit_id).encode()).hexdigest()[:10] # Временный хэш для красоты
    )

    # 3. Рендеринг через Playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_content(html_content)
        # Ждем загрузки всех стилей
        await page.wait_for_load_state("networkidle")
        pdf_bytes = await page.pdf(
            format="A4", 
            print_background=True,
            margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"}
        )
        await browser.close()
        return pdf_bytes

@celery_app.task
def generate_document_task(audit_id: int, user_id: str, doc_type: str):
    db: Session = SessionLocal()
    
    try:
        # 1. Генерация
        pdf_bytes = asyncio.run(render_pdf_with_playwright(audit_id, user_id, doc_type))
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        
        # 2. Путь (организуем файлы по папкам-типам)
        year = datetime.now().year
        file_name = f"{audit_id}_{doc_type}_{user_id}.pdf"
        file_path = f"{doc_type}/{year}/{file_name}"
        
        # 3. MinIO
        minio_client = get_minio_client()
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=file_path,
            data=BytesIO(pdf_bytes),
            length=len(pdf_bytes),
            content_type="application/pdf"
        )
        
        # 4. Обновляем статус в AuditTrail
        audit_record = db.query(models.AuditTrail).filter(models.AuditTrail.id == audit_id).first()
        if audit_record:
            audit_record.status = "DOCUMENT_SIGNED_PEP"
            audit_record.metadata_info = {
                "file_path": file_path, # Важно: ключ file_path используется в main.py для скачивания
                "sha256_hash": file_hash,
                "bucket": BUCKET_NAME
            }
            db.commit()

        # 5. Опционально: Обновляем статус в AssignedDocument
        assign_record = db.query(models.AssignedDocument).filter(
            models.AssignedDocument.user_id == user_id,
            models.AssignedDocument.document_type == doc_type
        ).first()
        if assign_record:
            assign_record.status = "SIGNED"
            db.commit()
            
        return {"status": "success", "file": file_path}
        
    except Exception as e:
        db.rollback()
        # Обновляем статус на ошибку, чтобы фронтенд перестал крутить лоадер
        audit_record = db.query(models.AuditTrail).filter(models.AuditTrail.id == audit_id).first()
        if audit_record:
            audit_record.status = "ERROR"
            audit_record.metadata_info = {"error": str(e)}
            db.commit()
        raise e
    finally:
        db.close()