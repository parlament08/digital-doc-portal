from sqlalchemy import Column, Integer, String, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid

Base = declarative_base()

class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    event_type = Column(String(50), nullable=False) # 'DOCUMENT_SIGNED', 'WORKFLOW_STARTED'
    user_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(UUID(as_uuid=True), nullable=False)
    document_hash = Column(String, nullable=False)
    metadata_info = Column("metadata", JSON) # JSONB в Postgres: IP, User-Agent
    prev_row_hash = Column(String)
    signature_hash = Column(String)