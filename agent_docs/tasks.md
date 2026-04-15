# Project Tasks & Backlog

## Current Priority Task: Codebase Translation & JWT Auth Setup

1.  **Translation (Ongoing):** Translate all Russian variables, comments, and UI elements to English as you edit files across the project.
2.  **Authentication Implementation:**
    * Currently, user IDs are hardcoded in the frontend.
    * **Goal:** Implement JWT Authentication in FastAPI.
    * Create a `User` model (and generate an Alembic migration).
    * Create a `/login` endpoint returning a Bearer Token.
    * Update the Vue applications in `/frontend/static/` to store the token and send it in the `Authorization` header.
    * Extract `user_id` and `role` securely from the token on the backend.

## Future Tasks:
* **PDF Generation:** Update `backend/app/worker.py` and `backend/app/templates/` to use real PDF generation libraries (e.g., `pdfkit` or `WeasyPrint`) combined with Jinja2 to render dynamic employee data into physical PDFs.
* **Frontend Migration:** Eventually migrate `/frontend/static/` HTML files into a modern Node.js/Vite build process.