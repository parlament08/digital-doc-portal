import os
import logging
from minio import Minio
from minio.error import S3Error
from io import BytesIO

logger = logging.getLogger(__name__)

class MinioService:
    def __init__(self):
        minio_url = os.getenv("MINIO_URL", "minio:9000").replace("http://", "")
        access_key = os.getenv("MINIO_ACCESS_KEY", "admin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "password123")
        self.bucket_name = os.getenv("MINIO_BUCKET", "signed-documents")
        
        self.client = Minio(
            minio_url,
            access_key=access_key,
            secret_key=secret_key,
            secure=False 
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Бакет '{self.bucket_name}' успешно создан.")
        except Exception as e:
            logger.error(f"Ошибка при проверке/создании бакета MinIO: {e}")

    def upload_pdf(self, file_name: str, pdf_bytes: bytes) -> str:
        """
        Загружает PDF в MinIO и возвращает object_name (ключ файла) для сохранения в БД.
        """
        pdf_stream = BytesIO(pdf_bytes)
        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=file_name,
                data=pdf_stream,
                length=len(pdf_bytes),
                content_type="application/pdf"
            )
            return file_name # Возвращаем чистый путь (например: 'campaigns/5/doc.pdf')
        except S3Error as e:
            logger.error(f"Ошибка загрузки файла {file_name} в MinIO: {e}")
            raise e
        
        
    def get_pdf(self, file_name: str) -> bytes:
        """
        Скачивает PDF из MinIO и возвращает его в виде сырых байтов.
        """
        try:
            response = self.client.get_object(self.bucket_name, file_name)
            pdf_bytes = response.read()
            return pdf_bytes
        except Exception as e:
            logger.error(f"Ошибка скачивания файла {file_name} из MinIO: {e}")
            raise e
        finally:
            # Обязательно закрываем соединение, чтобы не было утечек памяти
            if 'response' in locals():
                response.close()
                response.release_conn()