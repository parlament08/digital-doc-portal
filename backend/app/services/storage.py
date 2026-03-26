import os
from minio import Minio
from io import BytesIO

class MinioService:
    def __init__(self):
        minio_url = os.getenv("MINIO_URL", "minio:9000").replace("http://", "")
        access_key = os.getenv("MINIO_ACCESS_KEY", "admin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "password123")
        
        self.client = Minio(
            minio_url,
            access_key=access_key,
            secret_key=secret_key,
            secure=False 
        )
        self.bucket_name = "signed-documents"
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)

    def upload_pdf(self, file_name: str, pdf_bytes: bytes):
        pdf_stream = BytesIO(pdf_bytes)
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=file_name,
            data=pdf_stream,
            length=len(pdf_bytes),
            content_type="application/pdf"
        )
        return f"/{self.bucket_name}/{file_name}"