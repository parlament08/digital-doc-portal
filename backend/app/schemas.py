from pydantic import BaseModel
from typing import List

class CampaignCreateRequest(BaseModel):
    title: str
    document_type: str
    hr_director_id: str
    employee_ids: List[str] # Список ID сотрудников (например, ["emp_001", "emp_002"])