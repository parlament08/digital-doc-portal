import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Берем URL базы из переменных окружения (которые мы прописали в docker-compose)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/doc_portal")

# engine - это само подключение
engine = create_engine(DATABASE_URL, echo=False)

# SessionLocal - это фабрика сессий для наших эндпоинтов
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Зависимость (Dependency) для FastAPI, чтобы каждый запрос получал свою сессию БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()