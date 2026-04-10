import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base 

class SystemRole(str, enum.Enum):
    HR_SPECIALIST = "hr_specialist"
    HR_DIRECTOR = "hr_director"
    IT_DIRECTOR = "it_director"
    SYS_ADMIN = "sys_admin"
    ACCOUNTING = "accounting"
    EMPLOYEE = "employee"

class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)        
    document_type = Column(String)            
    
    # Связь с шагами (каскадное удаление, если удалим шаблон)
    steps = relationship("WorkflowStep", back_populates="template", cascade="all, delete-orphan", order_by="WorkflowStep.step_order")

class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("workflow_templates.id"))
    step_order = Column(Integer)              
    role_required = Column(String)            
    is_final = Column(Boolean, default=False) 
    
    template = relationship("WorkflowTemplate", back_populates="steps")