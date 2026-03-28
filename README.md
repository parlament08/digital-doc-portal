# Digital Doc Portal (Enterprise MVP)

Welcome to the **Digital Doc Portal**, a highly resilient, microservices-based system designed for legally significant electronic document management. This project enables users to sign internal documents (like Safety Instructions) using a Simple Electronic Signature (PEP) while ensuring an immutable audit trail, automated PDF generation, and enterprise-grade asynchronous processing.

## Tech Stack
* **Backend API:** FastAPI (Python 3.10)
* **Background Tasks:** Celery (using PostgreSQL as the message broker and result backend)
* **Database:** PostgreSQL 15
* **Storage:** MinIO (S3-compatible object storage)
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

Ensure `doc_portal_db`, `doc_portal_minio`, `doc_portal_api`, and `doc_portal_worker` are all in the **Up** state.

## 3. Monitor the Background Worker

Unlike previous versions, **you do not need to start the worker manually**. It runs automatically as a dedicated Docker service. To watch the background PDF generation in real-time, tail the worker logs:

```bash
docker logs -f doc_portal_worker
```
*(Press `Ctrl+C` to exit the log view).*

---

## Services & Ports Mapping

Once everything is running, you can access the various components via the following local URLs:

| Service | URL / Port | Description | Credentials |
| :--- | :--- | :--- | :--- |
| **FastAPI Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) | OpenAPI documentation & interactive API testing. | N/A |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | S3 Storage Administration UI. | `admin` / `password123` |
| **MinIO API** | `localhost:9000` | Internal port for S3 SDK connections. | N/A |
| **PostgreSQL** | `localhost:5433` | Database connection port (mapped to 5432 internally). | `user` / `password` |

---

## The Core Workflow (How it Works)

Understanding the data flow is crucial for maintaining and scaling the system:

1. **Trigger:** The user (or frontend) calls the `POST /api/sign` endpoint via FastAPI.
2. **API Validation:** FastAPI receives the data, creates a `GENERATION_IN_PROGRESS` audit record in Postgres, and immediately returns a `200 OK` with a `task_id`.
3. **Task Dispatch:** FastAPI sends an asynchronous task to the **Celery Queue** (routed through Postgres).
4. **Execution:** The Celery Worker (`doc_portal_worker`) picks up the task.
5. **Heavy Lifting:** The Worker uses **Jinja2** to inject dynamic data into an HTML template, launches a headless **Playwright** Chromium browser to render it into a pixel-perfect PDF, calculates the SHA-256 hash, and uploads the file to MinIO.
6. **Finalization:** The Worker updates the Postgres audit record status to `DOCUMENT_SIGNED_PEP`.

---

## Chaos Engineering: Testing Resilience

You can prove the enterprise reliability of this system by simulating a catastrophic failure:

1. Stop the Worker container completely: `docker compose stop worker`
2. Send a "Sign Document" request via Swagger (`/api/sign`).
3. Notice the API still responds instantly (the task is safely stored in the queue).
4. Restart the Worker: `docker compose start worker`
5. Watch the Worker logs: it will instantly pick up the pending task, generate the PDF, and save the file without losing any data!

---

## Troubleshooting Guide

### 1. "Connection Refused" to Database
If the API or Worker crashes with a Postgres connection error, it usually means the database was still booting up. 
**Fix:** We have implemented a `depends_on: condition: service_healthy` in `docker-compose.yml` to prevent this, but if it happens, simply restart the services:
`docker compose restart backend worker`

### 2. Playwright "Missing Dependencies" Error
If the worker throws an error about missing libraries (like `libpango` or `libcairo`), it means the Dockerfile is not using the official Microsoft image.
**Fix:** Ensure your `backend/Dockerfile` starts with `FROM mcr.microsoft.com/playwright/python:v1.41.1-jammy` and rebuild the images using `docker compose build --no-cache`.

### 3. Database Schema / Alembic Errors
If you changed SQLAlchemy models and need to start fresh (and don't mind losing local dev data), wipe the Docker volumes.
**Fix:** Run `docker compose down -v` to destroy the containers and volumes, then rebuild with `docker compose up -d --build`.