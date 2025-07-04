# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from yandex_cloud_ml_sdk import YCloudML
import json
import re
from dotenv import load_dotenv
import os

app = FastAPI()

origins = [
    "http://localhost:3000",   # адрес фронтенда
    "http://127.0.0.1:3000",
    # можно добавить другие адреса или ["*"] для всех (не рекомендуется в проде)
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  
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
