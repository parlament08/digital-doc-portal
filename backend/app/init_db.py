from sqlalchemy.orm import Session
from app.models.workflow import WorkflowTemplate, WorkflowStep, SystemRole

def init_workflow_templates(db: Session):
    # Список шаблонов с жесткой привязкой к типу документа
    templates_to_create = [
        {
            "name": "Стандартный КЭДО (NDA)",
            "doc_type": "nda_2026",
            "steps": [
                {"order": 1, "role": SystemRole.HR_DIRECTOR, "final": False},
                {"order": 2, "role": SystemRole.EMPLOYEE, "final": True}
            ]
        },
        {
            "name": "Инструктаж по ТБ",
            "doc_type": "safety_instruction_2026",
            "steps": [
                {"order": 1, "role": SystemRole.HR_DIRECTOR, "final": False},
                {"order": 2, "role": SystemRole.EMPLOYEE, "final": True}
            ]
        },
        {
            "name": "Удаленная работа (Политика)",
            "doc_type": "remote_work_policy",
            "steps": [
                {"order": 1, "role": SystemRole.HR_DIRECTOR, "final": False},
                {"order": 2, "role": SystemRole.EMPLOYEE, "final": True}
            ]
        }
    ]

    for t_data in templates_to_create:
        existing = db.query(WorkflowTemplate).filter(WorkflowTemplate.name == t_data["name"]).first()
        
        if not existing:
            print(f"BPM: Создаю шаблон '{t_data['name']}' с типом файла '{t_data['doc_type']}'...")
            
            # 1. Создаем шаблон
            new_template = WorkflowTemplate(
                name=t_data["name"],
                document_type=t_data["doc_type"]
            )
            db.add(new_template)
            db.commit()
            db.refresh(new_template)
            
            # 2. Создаем шаги
            for s_data in t_data["steps"]:
                step = WorkflowStep(
                    template_id=new_template.id,
                    step_order=s_data["order"],
                    role_required=s_data["role"],
                    is_final=s_data["final"]
                )
                db.add(step)
            
            db.commit()
            print(f"BPM: Шаблон '{t_data['name']}' успешно инициализирован.")

    print("BPM: Инициализация всех шаблонов завершена.")