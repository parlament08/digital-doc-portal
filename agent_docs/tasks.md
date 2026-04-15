# Project Tasks & Backlog

## TASK-1: Comprehensive UI Translation to English
**Status:** TODO
**Done when:** The custom tool `check_translation` returns `SUCCESS: No Russian characters found.`

### Scope & Constraints
* **Target Directory:** ONLY `frontend/static/*.html` (e.g., `hr_dashboard.html`, `hr_director.html`, `it_director.html`, `employee_cabinet.html`).
* **What to translate:** User-facing text, button labels, input placeholders, table headers, and SweetAlert (`Swal.fire`) titles/messages. Use B1/B2 level professional business English.
* **What NOT to translate:** Do not modify Vue.js reactive variables, API endpoint URLs, or core HTML structure. Do not touch backend Python files yet.

### Execution Steps for the Agent:
1. Open a single HTML file from the target directory.
2. Translate all Russian text to English.
3. Save the file.
4. **CRITICAL:** Call the `check_translation` tool.
5. If the tool returns a `FAIL` with line numbers, go back and fix the remaining Russian characters.
6. Repeat this process file by file until the tool returns a global `SUCCESS`.

---

## TASK-2: MSign Detached Signature Implementation
**Status:** TODO
**Done when:** All 5 technical steps below are implemented, Alembic migrations run without errors, and the system supports downloading a ZIP archive with the PDF and its detached signatures.

### Architecture Rules for this Task:
* We are using **Detached Signatures**. Do NOT modify the original PDF file.
* We sign the SHA-256 hash of the PDF, not the PDF itself.
* One document can have multiple signatures from different roles (stored in the database).

### Execution Steps for the Agent (Execute sequentially):

#### Step 1: Refactor Cryptography Utilities
* **File:** `backend/app/utils/signature.py`
* **Action:** Remove the `pyhanko` library and visual stamp logic completely.
* **Add Function 1:** `calculate_pdf_hash(file_bytes: bytes) -> str` (Must return the SHA-256 hex digest of the file).
* **Add Function 2:** `simulate_msign_api(hash_list: list[str], pin: str) -> dict` (A dummy function that takes a list of hashes and returns a dictionary mapping each hash to a fake cryptographic signature string like `msign_crypto_...`).

#### Step 2: Database Schema & Migration
* **File:** `backend/app/models/assigned_document.py`
* **Action:** Create a new SQLAlchemy model `DocumentSignature`.
* **Fields:** * `id` (Integer, Primary Key)
  * `document_id` (Integer, ForeignKey to `assigned_documents.id`)
  * `user_id` (String)
  * `role` (String)
  * `pdf_hash` (String)
  * `msign_crypto_code` (String)
  * `created_at` (DateTime, default utcnow)
* **Action:** Generate an Alembic migration for this new table (`alembic revision --autogenerate -m "add document signatures"`) and apply it (`alembic upgrade head`).

#### Step 3: Update Batch Signing Logic
* **File:** `backend/app/api/main.py` -> `sign_campaign_batch` endpoint.
* **Action:** Before updating `step_order`, fetch the PDF bytes from MinIO for each document.
* **Action:** Calculate the hash using `calculate_pdf_hash`.
* **Action:** Pass all hashes to `simulate_msign_api`.
* **Action:** Save the resulting crypto codes as new `DocumentSignature` records in the database.

#### Step 4: Update Individual Signing Logic
* **File:** `backend/app/api/main.py` -> `universal_sign_document` endpoint.
* **Action:** Apply the exact same logic from Step 3, but scoped to a single document (fetch PDF -> hash -> simulate MSign -> save to DB -> update step).

#### Step 5: Archive Download & UI Integration
* **File:** `backend/app/api/main.py`
* **Action:** Create `GET /api/documents/{user_id}/{doc_id}/download_archive`.
* **Logic:** Fetch the PDF from MinIO. Fetch all related `DocumentSignature` records. Create an in-memory ZIP file containing `document.pdf` and a `signatures.json` file (containing the DB records). Return the ZIP file as a `StreamingResponse` or `FileResponse`.
* **Files:** `frontend/static/employee_cabinet.html` and `frontend/static/hr_director.html`.
* **Action:** Add a "Download Signature Archive" button to the UI that hits this new endpoint.