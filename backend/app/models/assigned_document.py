from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base
from datetime import datetime

class AssignedDocument(Base):
    __tablename__ = "assigned_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)      # Кому назначили (напр. 'emp_001_andrey')
    document_type = Column(String)           # Что назначили (напр. 'nda_2026')
    status = Column(String, default="PENDING") # Статус: PENDING или SIGNED
    created_at = Column(DateTime, default=datetime.utcnow)