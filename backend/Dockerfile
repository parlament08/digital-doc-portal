FROM python:3.11-slim

WORKDIR /app

# 1. Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Магия Playwright: он сам скачает Chromium и установит все нужные apt-пакеты (libnss3, libxrandr2 и т.д.)
RUN playwright install --with-deps chromium

# 3. Копируем исходный код
COPY . .

# 4. Запускаем сервер
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]