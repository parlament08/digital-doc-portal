# Digital Doc Portal (Enterprise BPM & KEDO)

Welcome to the **Digital Doc Portal**, a highly resilient, microservices-based system designed for legally significant electronic document management (KEDO). This project enables HR departments to dynamically generate, route, and sign internal documents using a Simple Electronic Signature (MSign) while ensuring an immutable audit trail, automated PDF generation, and enterprise-grade asynchronous processing.

## 🚀 Tech Stack
* **Frontend:** Vue.js 3 (Composition API), Tailwind CSS, SweetAlert2 (Smart Tables with client-side pagination/filtering)
* **Backend API:** FastAPI (Python 3.10)
* **Database & Migrations:** PostgreSQL 15, SQLAlchemy ORM, Alembic
* **Background Tasks (Heavy):** Celery (with Redis/PostgreSQL broker) for PDF generation
* **Background Tasks (Light):** FastAPI `BackgroundTasks` for non-blocking email notifications
* **Storage:** MinIO (S3-compatible object storage for secure PDF streaming)
* **Email Testing:** Mailpit (Local SMTP server for catching notification emails)
* **PDF Rendering:** Playwright (Chromium Headless) + Jinja2 Templates
* **AI Agent Ready:** Pre-configured modular context for Anthropic's Claude Code (`.claudeignore`, `CLAUDE.md`, `agent_docs/`)

---

## 📁 Project Structure

The project has been refactored into a clean, decoupled architecture:

* `/backend/` - Contains the FastAPI app, Alembic migrations, models, services, and Jinja2 templates for PDF generation.
* `/frontend/static/` - User Interface HTML files (HR Dashboard, Employee Cabinet, Director Panels) using Vue 3.
* `/infra/` & `/data/` - Docker compose configurations, Postgres init scripts, and MinIO storage volumes.
* `/agent_docs/` - Modular knowledge base designed specifically for AI Agents (Claude Code) to understand the project architecture without context bloat.

---

## ⚙️ Prerequisites

Before deploying the project, ensure your environment meets the following requirements:
* **Docker:** Engine version 20.10+
* **Docker Compose:** Plugin version V2+
* **Node.js:** (Optional) If you plan to run Claude Code globally (`npm install -g @anthropic-ai/claude-code`).

---

## 1. Launch the Infrastructure

Run the following command in the root directory (where `docker-compose.yml` is located) to build and start all core services in detached mode:

```bash
docker compose up -d --build
```

> **Pro-Tip:** The first build might take a few minutes as it downloads the official Microsoft Playwright image (~1.5GB) which contains all necessary OS-level dependencies for perfect PDF rendering.

## 2. Verify Service Health

Give the system about 5-10 seconds to initialize. PostgreSQL has a configured `healthcheck`, so the API and Worker will wait for the database to be fully ready before starting. 

Check the status using:

```bash
docker compose ps
```

---

## 🌐 Services & Ports Mapping

Once everything is running, access the various roles and tools via the following local URLs:

| Service | URL / Port | Description | Credentials |
| :--- | :--- | :--- | :--- |
| **HR Specialist Panel** | [http://localhost:8000/hr](http://localhost:8000/hr) | BPM Dashboard to create campaigns and assign documents. | N/A |
| **HR Director Panel** | [http://localhost:8000/director/hr](http://localhost:8000/director/hr) | Batch signing interface (MSign) & Smart Archive. | N/A |
| **IT Director Panel** | [http://localhost:8000/director/it](http://localhost:8000/director/it) | Batch signing interface for IT-related routes. | N/A |
| **Employee Cabinet** | [http://localhost:8000/cabinet](http://localhost:8000/cabinet) | Workspace for employees to view and sign docs. | N/A |
| **Mailpit UI** | [http://localhost:8025](http://localhost:8025) | Catch-all email inbox for employee notifications. | N/A |
| **FastAPI Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) | OpenAPI documentation & interactive API testing. | N/A |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | S3 Storage Administration UI. | `admin` / `password123` |
| **PostgreSQL** | `localhost:5433` | Database connection port (mapped to 5432 internally). | `user` / `password` |

---

## 🔄 The Core Workflow (Universal BPM Engine)

The system no longer hardcodes statuses. It uses a dynamic state machine driven by `WorkflowTemplate` and `WorkflowStep` models:

1. **Initiation (HR Specialist):** HR selects a pre-defined route (e.g., "Safety Instruction") or builds a custom drag-and-drop route. A `DocumentCampaign` is created.
2. **Generation (Celery Worker):** The worker asynchronously compiles the PDF via Playwright, uploads it to MinIO, and sets the document's initial `step_order`.
3. **Smart Inbox Routing:** The `/api/bpm/inbox` endpoint dynamically calculates whose turn it is to sign by joining the document's current step with the required role.
4. **Batch Processing:** Directors can approve an entire campaign (e.g., 500 documents) via a single API request (`/api/bpm/campaigns/{id}/sign`) using an MSign PIN, executing within a single SQL transaction.
5. **Finalization:** When a document passes the step marked `is_final=True`, it automatically moves to the Smart Archive with a `FULLY_SIGNED` status.
6. **Audit Trail:** Every action is immutably logged in the `audit_trail` table.

---

## 🤖 AI Agent Integration (Claude Code)

This repository is optimized for **Claude Code**. 
1. Install the CLI: `npm install -g @anthropic-ai/claude-code`
2. Run `claude` in the root directory.
3. The agent will automatically read `CLAUDE.md` which acts as a router, pointing it to specific rules in `/agent_docs/` (Architecture, Frontend Rules, Tasks) without bloating the context window. Sensitive files are blocked via `.claudeignore` and `.claude/settings.json`.

---

## 🛠️ Troubleshooting Guide

### 1. Database Migrations (Alembic)
If you change the SQLAlchemy models in `backend/app/models/`, you must generate and apply a migration:
```bash
docker compose exec api alembic revision --autogenerate -m "description of changes"
docker compose exec api alembic upgrade head
```

### 2. "Connection Refused" to Database
If the API or Worker crashes with a Postgres connection error on the first boot, simply restart the services:
```bash
docker compose restart backend worker
```

### 3. Missing PDFs in Employee Cabinet
If the iframe shows an error: Ensure MinIO is running and the bucket exists. Check the Worker logs (`docker logs doc_portal_worker`) to confirm Playwright successfully rendered the file.

### 4. Database Reset (Clean Slate)
To wipe all assignments, campaigns, and audit logs for a fresh test run:
```bash
docker exec -it doc_portal_db psql -U user -d doc_portal -c "TRUNCATE document_campaigns, assigned_documents, audit_trail RESTART IDENTITY CASCADE;"