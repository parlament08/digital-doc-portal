# Digital Doc Portal (Enterprise MVP)

Welcome to the **Digital Doc Portal**, a highly resilient, microservices-based system designed for legally significant electronic document management (KEDO). This project enables HR departments to dynamically generate, route, and sign internal documents (like Safety Instructions and NDAs) using a Simple Electronic Signature (MSign/PEP) while ensuring an immutable audit trail, automated PDF generation, and enterprise-grade asynchronous processing.

## Tech Stack
* **Frontend:** Vue.js 3 (Composition API), Tailwind CSS, SweetAlert2 (Served via FastAPI)
* **Backend API:** FastAPI (Python 3.10)
* **Background Tasks (Heavy):** Celery (using PostgreSQL as the message broker) for PDF generation
* **Background Tasks (Light):** FastAPI `BackgroundTasks` for non-blocking email notifications
* **Database:** PostgreSQL 15 (relational data & audit logs)
* **Storage:** MinIO (S3-compatible object storage for clean PDFs)
* **Email Testing:** Mailpit (Local SMTP server for catching notification emails)
* **PDF Rendering:** Playwright (Chromium Headless) + Jinja2 Templates

---

## Prerequisites

Before deploying the project, ensure your environment meets the following requirements:
* **Docker:** Engine version 20.10+
* **Docker Compose:** Plugin version V2+

---

## 1. Launch the Infrastructure

Run the following command in the root directory (where `docker-compose.yml` is located) to build and start all core services in detached mode:

```bash
docker compose up -d --build
```

> **Pro-Tip:** The first build might take a few minutes as it downloads the official Microsoft Playwright image (~1.5GB) which contains all necessary OS-level dependencies (fonts, Cairo, Pango) for perfect PDF rendering.

## 2. Verify Service Health

Give the system about 5-10 seconds to initialize. PostgreSQL has a configured `healthcheck`, so the API and Worker will wait for the database to be fully ready before starting. 

Check the status using:

```bash
docker compose ps
```

Ensure `doc_portal_db`, `doc_portal_minio`, `doc_portal_api`, `mailpit`, and `doc_portal_worker` are all in the **Up** state.

---

## Services & Ports Mapping

Once everything is running, access the various roles and tools via the following local URLs. *(Note: UI templates are now served directly by FastAPI)*:

| Service | URL / Port | Description | Credentials |
| :--- | :--- | :--- | :--- |
| **HR Specialist Panel** | [http://localhost:8000/hr](http://localhost:8000/hr) | Dashboard to create campaigns and assign documents. | N/A |
| **HR Director Panel** | [http://localhost:8000/director/hr](http://localhost:8000/director/hr) | Batch signing interface (MSign) for the employer. | N/A |
| **Employee Cabinet** | [http://localhost:8000/cabinet](http://localhost:8000/cabinet) | Workspace for employees to view (PDF iframe) and sign docs. | N/A |
| **Mailpit UI** | [http://localhost:8025](http://localhost:8025) | Catch-all email inbox for employee notifications. | N/A |
| **FastAPI Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) | OpenAPI documentation & interactive API testing. | N/A |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | S3 Storage Administration UI. | `admin` / `password123` |
| **MinIO API** | `localhost:9000` | Internal port for S3 SDK connections. | N/A |
| **PostgreSQL** | `localhost:5433` | Database connection port (mapped to 5432 internally). | `user` / `password` |

---

## The Core Workflow (How it Works)

The system implements a strict state machine (`DRAFT` -> `WAITING_EMPLOYEE` -> `FULLY_SIGNED`) distributed across multiple microservices:

1. **Campaign Creation (HR Specialist):** HR selects employees and a document type. The API creates a campaign and dispatches tasks to Celery.
2. **PDF Generation (Celery Worker):** The worker uses Jinja2 to compile the text, Playwright to render a clean PDF, uploads it to MinIO, and updates the document status to `DRAFT`.
3. **Employer Signature (HR Director):** The HR Director reviews pending campaigns and signs them using an MSign PIN modal. The status changes to `WAITING_EMPLOYEE`.
4. **Asynchronous Notifications (FastAPI):** Immediately after the Director signs, FastAPI `BackgroundTasks` silently sends out email notifications via Mailpit without blocking the UI.
5. **Employee Signature:** The employee receives the email, logs into their Cabinet, views the pure PDF fetched directly from MinIO, and signs using their MSign PIN.
6. **Audit Trail:** Every action is immutably logged in the `audit_trail` table, serving as the single source of truth for the document's legal status.

---

## Chaos Engineering: Testing Resilience

You can prove the enterprise reliability of this system by simulating a catastrophic failure:

1. Stop the Worker container completely: `docker compose stop worker`
2. Create a new campaign via the HR Specialist UI.
3. Notice the frontend responds instantly (the generation tasks are safely stored in the PostgreSQL broker queue).
4. Restart the Worker: `docker compose start worker`
5. Watch the Worker logs (`docker logs -f doc_portal_worker`): it will instantly pick up the pending tasks, generate the PDFs, and upload them to MinIO without losing any data.

---

## Troubleshooting Guide

### 1. "Connection Refused" to Database
If the API or Worker crashes with a Postgres connection error, it usually means the database was still booting up. 
**Fix:** We have implemented a `depends_on: condition: service_healthy` in `docker-compose.yml`, but if it occurs, simply restart the services:

```bash
docker compose restart backend worker
```

### 2. Emails Not Arriving
If documents are signed by the HR Director but emails aren't showing up:
**Fix:** Verify the Mailpit container is running and accessible. Check the FastAPI logs (`docker logs doc_portal_api`) for SMTP connection errors.

### 3. Missing PDFs in Employee Cabinet
If the iframe shows an error instead of the document:
**Fix:** Ensure MinIO is running and the `signed-documents` bucket exists. Check the Worker logs to confirm Playwright successfully rendered and uploaded the file.

### 4. Database Reset (Clean Slate)
To wipe all assignments, campaigns, and audit logs for a fresh test run without rebuilding containers, execute:

```bash
docker exec -it doc_portal_db psql -U user -d doc_portal -c "TRUNCATE document_campaigns, assigned_documents, audit_trail RESTART IDENTITY CASCADE;"
```