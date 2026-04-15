# Backend & BPM Architecture

## 1. Project Layout (`/backend/`)
* `alembic/` & `alembic.ini` - Database migration engine. Always generate a new migration after modifying models.
* `app/api/main.py` - FastAPI entry point and endpoint definitions.
* `app/models/` - SQLAlchemy models (`assigned_document.py`, `workflow.py`, `audit.py`).
* `app/services/storage.py` - External integrations (MinIO).
* `app/celery_app.py` & `app/worker.py` - Background task configuration for heavy operations.
* `app/utils/signature.py` - Utilities for document signing logic.

## 2. Database Schema (BPM Core)
The system uses a dynamic Business Process Management (BPM) engine.
* `WorkflowTemplate` & `WorkflowStep`: Blueprints and steps for routing (e.g., step 1: HR, step 2: Employee).
* `DocumentCampaign`: A batch process entity grouping multiple documents sent at once.
* `AssignedDocument`: The actual document linked to an employee. Tracks `current_step_order`, `status` (DRAFT, IN_PROGRESS, FULLY_SIGNED).
* `AuditTrail`: Logs all system actions.

## 3. Core Mechanisms
* **Routing:** Documents move via `/api/bpm/documents/{doc_id}/sign`. The backend checks the current `WorkflowStep` role requirement. If valid, it increments `current_step_order`.
* **Batch Signing:** Directors use `/api/bpm/campaigns/{campaign_id}/sign` to process hundreds of documents in a single SQL transaction.
* **Storage:** PDFs are stored in MinIO and streamed to the frontend via dedicated endpoints to secure file access.