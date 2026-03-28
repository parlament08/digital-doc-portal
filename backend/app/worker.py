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
from app.models.audit import AuditTrail

# Данные для доступа к MinIO (в идеале вынести в .env, но для MVP можно так)
MINIO_URL = os.environ.get("MINIO_URL", "minio:9000")
MINIO_USER = os.environ.get("MINIO_ROOT_USER", "admin")
MINIO_PASS = os.environ.get("MINIO_ROOT_PASSWORD", "password123")
BUCKET_NAME = "signed-documents"

def get_minio_client():
    """Подключаемся к хранилищу MinIO"""
    client = Minio(MINIO_URL, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=False)
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)
    return client

async def render_pdf_with_playwright(audit_id: int, user_id: str, doc_type: str) -> bytes:
    """Асинхронная генерация PDF через "безголовый" браузер Chromium и Jinja2"""
    
    # 1. Настраиваем Jinja2 на чтение из папки app/templates
    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.get_template("safety_instruction.html")
    
    # 2. Рендерим HTML, подставляя наши данные
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    html_content = template.render(
        audit_id=audit_id,
        user_id=user_id,
        doc_type=doc_type,
        date=current_date
    )

    # 3. Отправляем готовый HTML в браузер
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.set_content(html_content)
        # Отключаем печать фона, чтобы цвета блока подписи сохранились
        pdf_bytes = await page.pdf(format="A4", print_background=True)
        
        await browser.close()
        return pdf_bytes

@celery_app.task(name="app.worker.generate_document_task")
def generate_document_task(audit_id: int, user_id: str, doc_type: str):
    """Главная задача Celery"""
    db: Session = SessionLocal()
    
    try:
        # 1. Генерируем PDF (запускаем асинхронный Playwright внутри синхронного Celery)
        pdf_bytes = asyncio.run(render_pdf_with_playwright(audit_id, user_id, doc_type))
        
        # 2. Вычисляем неизменяемый хэш документа (SHA-256)
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        
        # 3. Формируем путь для сохранения файла в MinIO
        file_name = f"{audit_id}_{doc_type}_{user_id}.pdf"
        file_path = f"{doc_type}/2026/{file_name}"
        
        # 4. Сохраняем физический файл в MinIO
        minio_client = get_minio_client()
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=file_path,
            data=BytesIO(pdf_bytes),
            length=len(pdf_bytes),
            content_type="application/pdf"
        )
        
        # 5. Триумф! Обновляем статус в базе данных на "Успешно подписан"
        audit_record = db.query(AuditTrail).filter(AuditTrail.id == audit_id).first()
        if audit_record:
            audit_record.status = "DOCUMENT_SIGNED_PEP"
            audit_record.metadata_info = {
                "minio_path": file_path,
                "sha256_hash": file_hash,
                "bucket": BUCKET_NAME
            }
            db.commit()
            
        return {"status": "success", "audit_id": audit_id, "hash": file_hash}
        
    except Exception as e:
        # Если что-то упало (нет связи с MinIO и тд), записываем ошибку в БД
        db.rollback()
        audit_record = db.query(AuditTrail).filter(AuditTrail.id == audit_id).first()
        if audit_record:
            audit_record.status = "ERROR"
            audit_record.metadata_info = {"error_message": str(e)}
            db.commit()
        raise e
    finally:
        db.close() # Обязательно закрываем сессию БД