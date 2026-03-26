import os
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

class PDFGenerator:
    def __init__(self):
        template_dir = "/app/templates"
        self.env = Environment(loader=FileSystemLoader(template_dir))

    async def create_safety_doc(self, employee_name: str, doc_id: str, date: str) -> bytes:
        template = self.env.get_template("safety_instruction.html")
        html_content = template.render(
            employee_name=employee_name,
            document_id=doc_id,
            date=date
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.set_content(html_content)
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            
            await browser.close()
            return pdf_bytes