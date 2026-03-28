from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, index=True)
    
    # Кто подписывает (например, табельный номер или логин)
    user_id = Column(String, index=True, nullable=False)
    
    # Что подписывает (например, 'safety_instruction')
    document_type = Column(String, nullable=False)
    
    # Статус процесса: GENERATION_IN_PROGRESS -> DOCUMENT_SIGNED_PEP -> ERROR
    status = Column(String, default="GENERATION_IN_PROGRESS")
    
    # Когда нажали кнопку
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Гибкое JSON-поле. Сюда мы запишем путь в MinIO, хэш файла и IP-адрес
    metadata_info = Column(JSON, default={})