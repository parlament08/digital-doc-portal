# Frontend & UI Guidelines

## 1. Directory Structure Rule
* **UI Dashboards:** Located in `/frontend/static/` (e.g., `hr_dashboard.html`, `employee_cabinet.html`). These use Vue 3 via CDN.
* **PDF Templates:** Located in `/backend/app/templates/` (e.g., `safety_instruction.html`, `doc_template.html`). These are used by the backend/Celery to render PDF files. Do not mix them up.

## 2. Vue 3 Guidelines (for `/frontend/static/`)
* Use **Vue 3 via CDN** and **TailwindCSS via CDN**.
* Always use the **Composition API** (`setup()`, `ref`, `computed`, `watch`, `onMounted`). Do not use the Options API.
* Use `Swal.fire` (SweetAlert2) for alerts and PIN-code inputs.

## 3. Smart Tables (Client-Side)
For pages with many records (Director Archives, HR Dashboards):
* Use reactive client-side pagination (default 10 items per page).
* Apply sequential filtering using `computed` properties (dropdown type filter -> string search query).
* Do not make excessive API calls for sorting/searching; handle it within the Vue component using the fetched dataset.

## 4. Global Translation Rule
The project is currently mixed (Russian/English). **All UI text, placeholders, SweetAlert messages, and code comments must be translated to English.** When you edit an HTML file in `/frontend/static/`, automatically translate its Russian UI elements to English.