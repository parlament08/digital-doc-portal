# Digital Doc Portal (Enterprise MVP)

Welcome to the **Digital Doc Portal**, a highly resilient, microservices-based system designed for legally significant electronic document management. This project enables users to sign internal documents (like Safety Instructions) using a Simple Electronic Signature (PEP) while ensuring an immutable audit trail and enterprise-grade asynchronous processing.

---

## Prerequisites

Before deploying the project, ensure your environment meets the following requirements:
- **Docker:** Engine version 20.10+
- **Docker Compose:** Plugin version V2+
- **Python 3.10+** (if running the worker locally outside of Docker)

---

## 1. Launch the Infrastructure

Run the following command in the root directory (where `docker-compose.yml` is located) to build and start all core services in detached mode:

```bash
docker compose up -d --build
```

> **Pro-Tip:** The `--build` flag ensures that any recent changes to your `requirements.txt` (like adding `temporalio`) are baked into the new FastAPI image.

## 2. Verify Service Health

Give the system about 15-30 seconds to initialize, especially for Temporal to run its database migrations. Check the status using:

```bash
docker compose ps
```
Ensure `db`, `minio`, `temporal`, `temporal-ui`, and `backend` are all in the `Up` state.

## 3. Start the Background Worker

The API will accept tasks, but without a worker, they will sit in the Temporal queue. To start processing, launch the worker inside the running API container:

```bash
docker exec -it doc_portal_api python -m app.worker
```
You should see the following success message in the terminal:
`🚀 Temporal Worker successfully connected to temporal:7233 and is waiting for tasks...`

Leave this terminal window open.

---

## Services & Ports Mapping

Once everything is running, you can access the various components via the following local URLs:

| Service           | URL                       | Description                                       | Credentials         |
| :---------------- | :------------------------ | :------------------------------------------------ | :------------------ |
| Frontend Portal   | `frontend/index.html`     | The user-facing Vue.js application.               | N/A                 |
| FastAPI Swagger   | `http://localhost:8000/docs` | OpenAPI documentation for backend testing.        | N/A                 |
| Temporal UI       | `http://localhost:8082`   | Observability dashboard for background workflows. | N/A                 |
| MinIO Console     | `http://localhost:9001`   | S3 Storage Administration UI.                     | `admin` / `*****` |
| PostgreSQL        | `localhost:5433`          | Database connection port.                         | `user` / `*****` |

---

## The Core Workflow (How it Works)

Understanding the data flow is crucial for maintaining and scaling the system.

1.  **Trigger:** The user clicks "Acknowledge and Sign" on the Frontend.
2.  **API Validation:** FastAPI receives the `user_id`, checks Postgres to ensure the user hasn't already signed this document, and creates a `GENERATION_IN_PROGRESS` audit record.
3.  **Task Dispatch:** FastAPI sends a `DocumentWorkflow` task to the Temporal Server and immediately returns a `200 OK` (Status: Processing) to the Frontend.
4.  **Execution:** The Temporal Server assigns the task to the Python Worker.
5.  **Heavy Lifting:** The Worker runs the `generate_document_activity`. It renders the PDF, hashes it, uploads it to MinIO, and updates the Postgres audit record to `DOCUMENT_SIGNED_PEP`.
6.  **Retrieval:** When the user refreshes or clicks the document link, FastAPI fetches the clean S3 path from the database and streams the PDF directly from MinIO.

---

## Chaos Engineering: Testing Resilience

You can prove the enterprise reliability of this system by simulating a catastrophic failure:

1.  Stop the Worker terminal (`Ctrl+C`).
2.  Click the "Sign Document" button on the Frontend.
3.  Notice the Frontend still responds instantly.
4.  Open **Temporal UI** (Port 8082). You will see the workflow in a `Running` state, with the activity `Pending`.
5.  Restart the Worker (`docker exec -it doc_portal_api python -m app.worker`).
6.  Watch Temporal instantly assign the pending task to the worker, complete the generation, and save the file without losing any data.

---

## Troubleshooting Guide

### 1. Temporal UI shows 500 Internal Error
This usually means the Temporal server hasn't finished configuring the PostgreSQL database yet.
**Fix:** Wait 30 seconds and refresh the page.

### 2. "Connection Refused" in Worker Logs
If you run the worker on your host machine instead of inside Docker, it won't be able to resolve `temporal:7233`.
**Fix:** Always run the worker inside the Docker network using:
```bash
docker exec -it doc_portal_api python -m app.worker
```

### 3. S3 NoSuchKey Error when downloading PDFs
This indicates a mismatch between the bucket name and the object path saved in the database.
**Fix:** Ensure your download endpoint in `main.py` strips the `/signed-documents/` bucket prefix from the `file_path` before querying MinIO.

### 4. Database Schema Errors
If you changed SQLAlchemy models and need to start fresh, drop and recreate the tables.
**Fix:** Connect to the DB container and truncate the tables:
```bash
docker exec -it doc_portal_db psql -U user -d doc_portal -c "TRUNCATE TABLE audit_trail;"
```