import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base

# ==========================================
# 1. ENUMS (Строгие статусы для стейт-машины)
# ==========================================

class CampaignStatus(str, enum.Enum):
    GENERATING_PDFS = "GENERATING_PDFS"
    WAITING_HR_DIRECTOR = "WAITING_HR_DIRECTOR"
    WAITING_EMPLOYEES = "WAITING_EMPLOYEES"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"

class DocStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    WAITING_EMPLOYEE = "WAITING_EMPLOYEE"
    IN_PROGRESS = "IN_PROGRESS"           
    FULLY_SIGNED = "FULLY_SIGNED"
    ERROR = "ERROR"

# ==========================================
# 2. МОДЕЛИ БАЗЫ ДАННЫХ
# ==========================================

class DocumentCampaign(Base):
    __tablename__ = "document_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)             
    document_type = Column(String, nullable=False)     
    created_by_hr_id = Column(String, nullable=False)  
    hr_director_id = Column(String, nullable=False)       
    status = Column(Enum(CampaignStatus), default=CampaignStatus.GENERATING_PDFS)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    batch_signature_hash = Column(String, nullable=True) 

    # Связь с конкретными документами сотрудников
    documents = relationship("AssignedDocument", back_populates="campaign", cascade="all, delete-orphan")


class AssignedDocument(Base):
    __tablename__ = "assigned_documents"

    id = Column(Integer, primary_key=True, index=True)
    
    # Связь с кампанией
    campaign_id = Column(Integer, ForeignKey("document_campaigns.id"), nullable=False)
    user_id = Column(String, index=True, nullable=False)
    status = Column(Enum(DocStatus), default=DocStatus.DRAFT)
    
    # Файлы в MinIO
    original_pdf_path = Column(String, nullable=True)         
    director_signed_pdf_path = Column(String, nullable=True)  
    final_signed_pdf_path = Column(String, nullable=True)     

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))

    # BPM: Маршруты
    workflow_template_id = Column(Integer, ForeignKey("workflow_templates.id"), nullable=True)
    current_step_order = Column(Integer, default=1)
    
    # Обратные связи
    campaign = relationship("DocumentCampaign", back_populates="documents")
    workflow_template = relationship("WorkflowTemplate")