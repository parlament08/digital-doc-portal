# Digital Doc Portal (BPM / KEDO System)

**Tech Stack:** FastAPI (Python), SQLAlchemy, Alembic, PostgreSQL, Celery, Vue 3 (CDN), TailwindCSS.

**Project Structure Overview:**
* `backend/` - Contains the FastAPI application, Alembic migrations, and background workers.
  * `app/api/main.py` - Core API router.
  * `app/templates/` - HTML templates strictly for generating PDF documents.
* `frontend/static/` - User Interface HTML files (Dashboards, Cabinets) using Vue 3 and Tailwind.
* `infra/` & `data/` - Docker, PostgreSQL init scripts, and MinIO storage.

## Documentation Index (Read only when relevant to the task):
* **Backend, DB, & BPM Logic:** Read `agent_docs/architecture.md`.
* **UI & Client-Side Logic:** Read `agent_docs/frontend_rules.md`.
* **Current Backlog:** Read `agent_docs/tasks.md`.

## Core Directives:
* **Translation Rule:** We are transitioning the entire application to English. All new code, comments, variables, HTML text, and UI elements MUST be written in English. Do not write Russian text in the codebase.
* Always check the precise file paths before making changes. Frontend UI is in `frontend/static/`, not in the backend folder.