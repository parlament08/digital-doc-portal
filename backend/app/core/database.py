import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Берем URL базы данных из переменных окружения Docker
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://user:password@db:5432/doc_portal"
)

# Создаем движок SQLAlchemy
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency для FastAPI (будет выдавать сессию для каждого запроса)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()