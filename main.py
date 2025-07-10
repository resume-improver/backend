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
import io
import fitz
import requests
from fastapi.responses import JSONResponse

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
    messages = [
        {
            'role': 'system',
            'text': (
                'Ты помощник соискателя. Твоя задача - помочь соискателю составить привлекательное для работодателя профессиональное резюме. '
                'Составь оценочную характеристику резюме. Укажи на недостатки и предложи изменения. После чего - составь черновой вариант изменения, опираясь на предложенные правки. '
                'Используй информацию из предложенных резюме и вакансии. '
                'Не указывай ложную информацию в резюме. '
                'Не рекомендуй пользователю лгать в резюме.'
            )
        },
        {
            'role': 'user',
            'text': f'Резюме:\n{resume}\n\nдля вакансии:\n{vacancy}'
        }
    ]
    response = get_yandexgpt_response(messages)
    text = extract_text(response)
    cleaned = clean_json_text(text)
    return {"raw": cleaned}

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

def pdf_from_s3_to_text_array(s3_client, bucket, key):
    text_array = []
    try:
        pdf_stream = io.BytesIO()
        s3_client.download_fileobj(bucket, key, pdf_stream)
        pdf_stream.seek(0)
        with fitz.open(stream=pdf_stream.read(), filetype="pdf") as doc:
            for page in doc:
                text_array.append(page.get_text())
    except Exception as e:
        print(f"Ошибка при чтении PDF из S3: {e}")
    return text_array

def extract_resume_json(resume_text_array):
    resume_text = "\n".join(resume_text_array)
    system_prompt = (
        "Ты помощник, который преобразует текст резюме в структурированный JSON. "
        "Верни только JSON следующей структуры (если что-то не найдено — оставь пустым) или добавь в отдельный пункт то, чего нет в списке:\n"
        "{\n"
        "  \"ФИО\": \"\",\n"
        "  \"Опыт_работы\": \"\",\n"
        "  \"Хард_скиллы\": [],\n"
        "  \"Софт_скиллы\": [],\n"
        "  \"Контакты\": \"\",\n"
        "  \"Образование\": \"\",\n"
        "  \"Проекты\": []\n"
        "}\n"
        "Не добавляй объяснений, только JSON!"
    )

    data = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt",
        "completionOptions": {"temperature": 0.3, "maxTokens": 3000},
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": resume_text}
        ]
    }

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    response = requests.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        headers=headers,
        json=data
    )

    try:
        result = response.json()
        answer = result["result"]["alternatives"][0]["message"]["text"]

        if answer.strip().startswith("```"):
            answer = answer.strip().strip("`")
            first_newline = answer.find("\n")
            answer = answer[first_newline + 1:]
            answer = answer.strip()

        parsed_json = json.loads(answer)
        return parsed_json

    except Exception as e:
        print("Ошибка при обработке ответа YandexGPT:", e)
        print("Ответ модели:\n", response.text)
        return None

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

    # Чтение PDF напрямую из S3
    resume_text_arr = pdf_from_s3_to_text_array(s3, YANDEX_S3_BUCKET, resume_key)
    vacancy_text_arr = pdf_from_s3_to_text_array(s3, YANDEX_S3_BUCKET, vacancy_key)

    resume_text = "\n".join(resume_text_arr)
    vacancy_text = "\n".join(vacancy_text_arr)

    letter = generate_cover_letter(resume_text, vacancy_text)
    improvements = improve_resume(resume_text, vacancy_text)

    return {
        "resume_improvements": improvements,
        "cover_letter_draft": extract_text(letter)
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
