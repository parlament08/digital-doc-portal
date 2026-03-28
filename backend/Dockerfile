# Официальный образ Microsoft с уже встроенным Chromium и всеми пакетами (на базе Ubuntu)
FROM mcr.microsoft.com/playwright/python:v1.41.1-jammy

WORKDIR /app

# Копируем и устанавливаем Python-библиотеки
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .