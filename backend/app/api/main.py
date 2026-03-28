from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import engine, Base, get_db
from app.models.audit import AuditTrail
from app.worker import generate_document_task

# Создаем таблицы в БД при старте сервера (удобно для MVP)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Digital Doc Portal API")

# Pydantic-модель для валидации входящего запроса
class SignRequest(BaseModel):
    user_id: str
    document_type: str

@app.post("/api/sign", summary="Подписать документ (асинхронно)")
def sign_document(request: SignRequest, db: Session = Depends(get_db)):
    """
    1. Создаем запись в журнале аудита со статусом В ПРОЦЕССЕ
    2. Отправляем тяжелую задачу в Celery
    3. Сразу отвечаем фронтенду, не заставляя пользователя ждать
    """
    
    # Шаг 1: Фиксируем намерение в БД
    audit_record = AuditTrail(
        user_id=request.user_id,
        document_type=request.document_type,
        status="GENERATION_IN_PROGRESS"
    )
    db.add(audit_record)
    db.commit()
    db.refresh(audit_record) # Получаем сгенерированный ID

    # Шаг 2: Отправляем задачу воркеру Celery (.delay - это метод Celery для фонового запуска)
    task = generate_document_task.delay(
        audit_id=audit_record.id, 
        user_id=request.user_id, 
        doc_type=request.document_type
    )

    # Шаг 3: Отвечаем фронтенду за 15 миллисекунд
    return {
        "message": "Документ отправлен на подписание и генерацию PDF",
        "audit_id": audit_record.id,
        "task_id": task.id
    }

@app.get("/api/documents/{user_id}", summary="Получить архив пользователя")
def get_user_documents(user_id: str, db: Session = Depends(get_db)):
    """ Отдает фронтенду список всех документов сотрудника """
    records = db.query(AuditTrail).filter(AuditTrail.user_id == user_id).order_by(AuditTrail.created_at.desc()).all()
    return records