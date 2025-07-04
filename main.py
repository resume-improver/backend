# main.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from yandex_cloud_ml_sdk import YCloudML
import json
import re
from dotenv import load_dotenv
import os
import boto3
from sqlalchemy import Column, Integer, String, DateTime, Enum, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import enum
from apscheduler.schedulers.background import BackgroundScheduler
import time

app = FastAPI()

origins = [
    "http://localhost:3000",   # адрес фронтенда
    "http://127.0.0.1:3000",
    "http://0.0.0.0:3000",
    # можно добавить другие адреса или ["*"] для всех (не рекомендуется в проде)
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ResumeRequest(BaseModel):
    resume_text: str
    vacancy_text: str

load_dotenv()

YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_S3_ENDPOINT = os.getenv("YANDEX_S3_ENDPOINT")
YANDEX_S3_ACCESS_KEY = os.getenv("YANDEX_S3_ACCESS_KEY")
YANDEX_S3_SECRET_KEY = os.getenv("YANDEX_S3_SECRET_KEY")
YANDEX_S3_BUCKET = os.getenv("YANDEX_S3_BUCKET")

# SQLAlchemy setup
Base = declarative_base()

class TaskStatus(str, enum.Enum):
    pending = 'pending'
    done = 'done'
    error = 'error'

class ResumeTask(Base):
    __tablename__ = 'resume_tasks'
    id = Column(Integer, primary_key=True, index=True)
    resume_url = Column(String, nullable=False)
    vacancy_url = Column(String, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    result = Column(String, nullable=True)  # поле для результата анализа

# Database connection from env
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "resume_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
DATABASE_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables if not exist
Base.metadata.create_all(bind=engine)

def get_yandexgpt_response(messages, temperature=0.5):
    sdk = YCloudML(
        folder_id=YANDEX_FOLDER_ID,
        auth=YANDEX_API_KEY,
    )
    result = (
        sdk.models.completions("yandexgpt").configure(temperature=temperature).run(messages)
    )
    return result[0].text if result else ""

def extract_text(response):
    if isinstance(response, dict) and "text" in response:
        return response["text"]
    return response

def clean_json_text(text):
    text = text.strip()
    # Remove ``` and optional language hint (e.g., ```json)
    text = re.sub(r"^```(?:json)?", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()

def generate_cover_letter(resume: str, vacancy: str) -> str:
    system_prompt = (
        "Ты карьерный консультант. Составь короткое сопроводительное письмо "
        "на русском языке, строго на основе текста резюме и описания вакансии. "
        "Не добавляй ничего, чего нет в резюме."
    )
    user_prompt = (
        f"Резюме:\n{resume}\n\n"
        f"Вакансия:\n{vacancy}\n\n"
        "Составь сопроводительное письмо (до 200 слов)."
    )

    messages = [
        {"role": "system", "text": system_prompt},
        {"role": "user", "text": user_prompt}
    ]
    response = get_yandexgpt_response(messages)
    return response

def improve_resume(resume: str, vacancy: str) -> dict:
    prompt = (
        "Ты карьерный консультант. Проанализируй следующее резюме на соответствие вакансии. "
        "Верни результат в формате JSON со следующей структурой:\n\n"
        "{\n"
        "  \"missing_skills\": [\"...\"],\n"
        "  \"suggested_rewordings\": [\n"
        "    {\"original\": \"...\", \"suggested\": \"...\"}\n"
        "  ],\n"
        "  \"block_order_suggestions\": [\n"
        "    {\"block\": \"...\", \"action\": \"move_up|add|remove\"}\n"
        "  ]\n"
        "}\n\n"
        "Не добавляй ничего, чего нет в резюме. Не придумывай факты.\n\n"
        f"Резюме:\n{resume}\n\nВакансия:\n{vacancy}"
    )

    messages = [
        {"role": "user", "text": prompt}
    ]
    response = get_yandexgpt_response(messages)
    text = extract_text(response)
    cleaned = clean_json_text(text)
    try:
        return json.loads(cleaned)
    except Exception as e:
        return {"error": "Failed to parse JSON", "raw": cleaned}

@app.post("/analyze")
async def analyze_resume(data: ResumeRequest):
    letter = generate_cover_letter(data.resume_text, data.vacancy_text)
    improvements = improve_resume(data.resume_text, data.vacancy_text)
    return {
        "resume_improvements": improvements,
        "cover_letter_draft": extract_text(letter)
    }

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=YANDEX_S3_ENDPOINT,
        aws_access_key_id=YANDEX_S3_ACCESS_KEY,
        aws_secret_access_key=YANDEX_S3_SECRET_KEY,
    )

@app.post("/upload_pdf")
async def upload_pdf(
    resume_file: UploadFile = File(...),
    vacancy_file: UploadFile = File(...)
):
    s3 = get_s3_client()
    resume_key = f"resumes/{resume_file.filename}"
    vacancy_key = f"vacancies/{vacancy_file.filename}"

    # Загрузка файлов в S3
    s3.upload_fileobj(resume_file.file, YANDEX_S3_BUCKET, resume_key)
    s3.upload_fileobj(vacancy_file.file, YANDEX_S3_BUCKET, vacancy_key)

    resume_url = f"{YANDEX_S3_ENDPOINT}/{YANDEX_S3_BUCKET}/{resume_key}"
    vacancy_url = f"{YANDEX_S3_ENDPOINT}/{YANDEX_S3_BUCKET}/{vacancy_key}"

    # Сохраняем задачу в базу данных
    db = SessionLocal()
    task = ResumeTask(
        resume_url=resume_url,
        vacancy_url=vacancy_url,
        status=TaskStatus.pending
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    db.close()

    return {
        "task_id": task.id,
        "resume_url": resume_url,
        "vacancy_url": vacancy_url,
        "status": task.status
    }

# --- Фоновый обработчик ---
def analyze_task(task: ResumeTask, db):
    # Заглушка: имитируем тяжелую обработку
    time.sleep(2)  # имитация задержки
    fake_result = f"Анализ завершен для задачи {task.id} (заглушка)"
    task.status = TaskStatus.done
    task.result = fake_result
    db.commit()


def background_analyze():
    db = SessionLocal()
    try:
        # Ищем первую задачу в статусе pending
        task = db.query(ResumeTask).filter(ResumeTask.status == TaskStatus.pending).first()
        if task:
            task.status = TaskStatus.done  # чтобы не схватил другой воркер, можно добавить статус processing
            db.commit()
            analyze_task(task, db)
    finally:
        db.close()

# Запуск APScheduler
scheduler = BackgroundScheduler()
scheduler.add_job(background_analyze, 'interval', seconds=10)
scheduler.start()
