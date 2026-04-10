import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base

# ==========================================
# 1. ENUMS (Строгие статусы для стейт-машины)
# ==========================================

class CampaignStatus(str, enum.Enum):
    GENERATING_PDFS = "GENERATING_PDFS"         # Воркеры рендерят пачку PDF
    WAITING_HR_DIRECTOR = "WAITING_HR_DIRECTOR" # Ждет пакетной подписи HR-Директора
    WAITING_EMPLOYEES = "WAITING_EMPLOYEES"     # HR-Директор подписал, ждем сотрудников
    COMPLETED = "COMPLETED"                     # Все подписали
    CANCELED = "CANCELED"                       # HR отменил рассылку

class DocStatus(str, enum.Enum):
    DRAFT = "DRAFT"                       # PDF рендерится или ждет HR-Директора
    WAITING_EMPLOYEE = "WAITING_EMPLOYEE" # HR-Директор подписал, появилось в кабинете
    IN_PROGRESS = "IN_PROGRESS"           
    FULLY_SIGNED = "FULLY_SIGNED"         # Сотрудник подписал через MSign
    ERROR = "ERROR"                       # Ошибка при генерации/подписании

# ==========================================
# 2. МОДЕЛИ БАЗЫ ДАННЫХ
# ==========================================

class DocumentCampaign(Base):
    """
    Родительская сущность: Массовая рассылка (Кампания)
    """
    __tablename__ = "document_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)             # Напр. 'NDA Q2 2026 - IT Отдел'
    document_type = Column(String, nullable=False)     # Напр. 'nda_2026'
    created_by_hr_id = Column(String, nullable=False)  # Кто запустил
    
    # ИЗМЕНЕНО: теперь явно указываем, что это HR Директор
    hr_director_id = Column(String, nullable=False)       
    
    status = Column(Enum(CampaignStatus), default=CampaignStatus.GENERATING_PDFS)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Хэш пакетной подписи от MSign (появится позже)
    batch_signature_hash = Column(String, nullable=True) 

    # Связь One-to-Many с конкретными документами сотрудников
    documents = relationship("AssignedDocument", back_populates="campaign", cascade="all, delete-orphan")


class AssignedDocument(Base):
    """
    Дочерняя сущность: Конкретный документ конкретного сотрудника
    """
    __tablename__ = "assigned_documents"

    id = Column(Integer, primary_key=True, index=True)
    
    # Связь с кампанией
    campaign_id = Column(Integer, ForeignKey("document_campaigns.id"), nullable=False)
    
    # Кому назначен
    user_id = Column(String, index=True, nullable=False)
    
    # Статус документа
    status = Column(Enum(DocStatus), default=DocStatus.DRAFT)
    
    # Жизненный цикл файла в MinIO (PAdES)
    original_pdf_path = Column(String, nullable=True)         # PDF без подписей
    director_signed_pdf_path = Column(String, nullable=True)  # PDF с 1-й подписью
    final_signed_pdf_path = Column(String, nullable=True)     # PDF с 2-мя подписями

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))

    # Обратная связь с кампанией
    campaign = relationship("DocumentCampaign", back_populates="documents")

    # Ссылка на шаблон маршрута, по которому идет этот документ
    workflow_template_id = Column(Integer, ForeignKey("workflow_templates.id"), nullable=True)
    
    # Текущий шаг (начинаем всегда с 1)
    current_step_order = Column(Integer, default=1)
    
    # Связь для удобного доступа к шаблону через ORM
    workflow_template = relationship("WorkflowTemplate")