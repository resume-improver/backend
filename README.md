# Resume Backend

## Описание

Сервис для загрузки PDF-файлов резюме и вакансии, хранения их в S3, постановки задач на анализ и хранения результатов в базе данных PostgreSQL. Фоновый обработчик автоматически анализирует задачи.

---

## Быстрый старт

### 1. Клонируйте репозиторий и перейдите в папку
```bash
cd backend
```

### 2. Установите зависимости
```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

### 3. Настройте переменные окружения
Создайте файл `.env` в корне проекта и заполните:
```
# Яндекс Облако S3
YANDEX_S3_ENDPOINT=https://storage.yandexcloud.net
YANDEX_S3_ACCESS_KEY=your-access-key
YANDEX_S3_SECRET_KEY=your-secret-key
YANDEX_S3_BUCKET=your-bucket-name

# Яндекс GPT
YANDEX_FOLDER_ID=your-folder-id
YANDEX_API_KEY=your-yandex-api-key

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=resume_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=yourpassword
```

### 4. Запустите PostgreSQL (локально через Docker)
```bash
docker run --name resume-pg -e POSTGRES_PASSWORD=yourpassword -e POSTGRES_DB=resume_db -p 5432:5432 -d postgres:15
```

### 5. Запустите сервис
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Сервис будет доступен по адресу: http://localhost:8000

---

## Основные эндпоинты

- `POST /upload_pdf` — загрузка PDF-файлов резюме и вакансии, постановка задачи
- `POST /analyze` — анализ резюме и вакансии (по тексту)

---
