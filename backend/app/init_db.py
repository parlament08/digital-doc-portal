from sqlalchemy.orm import Session
from app.models.workflow import WorkflowTemplate, WorkflowStep, SystemRole

def init_workflow_templates(db: Session):
    # Проверяем, есть ли уже в базе наш главный маршрут
    existing_template = db.query(WorkflowTemplate).filter(WorkflowTemplate.name == "Стандартный КЭДО").first()
    
    if not existing_template:
        print("BPM: Создаю базовый шаблон маршрута 'Стандартный КЭДО'...")
        
        # 1. Создаем сам шаблон
        base_template = WorkflowTemplate(
            name="Стандартный КЭДО",
            document_type="standard_nda" # Можешь указать свой тип по умолчанию
        )
        db.add(base_template)
        db.commit()
        db.refresh(base_template)
        
        # 2. Создаем Шаг 1: Подпись Директора
        step_1 = WorkflowStep(
            template_id=base_template.id,
            step_order=1,
            role_required=SystemRole.HR_DIRECTOR,
            is_final=False
        )
        
        # 3. Создаем Шаг 2: Подпись Сотрудника (Финальный)
        step_2 = WorkflowStep(
            template_id=base_template.id,
            step_order=2,
            role_required=SystemRole.EMPLOYEE,
            is_final=True
        )
        
        db.add(step_1)
        db.add(step_2)
        db.commit()
        print("BPM: Базовый маршрут успешно создан!")

    # Для примера: Давай сразу создадим маршрут для IT-отдела
    it_template = db.query(WorkflowTemplate).filter(WorkflowTemplate.name == "Выдача оборудования").first()
    if not it_template:
        print("BPM: Создаю шаблон 'Выдача оборудования'...")
        it_tmp = WorkflowTemplate(name="Выдача оборудования", document_type="equipment_act")
        db.add(it_tmp)
        db.commit()
        db.refresh(it_tmp)
        
        db.add_all([
            WorkflowStep(template_id=it_tmp.id, step_order=1, role_required=SystemRole.SYS_ADMIN, is_final=False),
            WorkflowStep(template_id=it_tmp.id, step_order=2, role_required=SystemRole.IT_DIRECTOR, is_final=False),
            WorkflowStep(template_id=it_tmp.id, step_order=3, role_required=SystemRole.EMPLOYEE, is_final=True)
        ])
        db.commit()
        print("BPM: Маршрут IT-отдела создан!")