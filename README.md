# Backend

This is a FastAPI backend for resume analysis and cover letter generation using YandexGPT.

## Features
- Generates a cover letter draft based on your resume and a job description
- Analyzes your resume for improvements tailored to a specific vacancy

## Requirements
- Python 3.8+
- [Poetry](https://python-poetry.org/docs/#installation)
- YandexGPT API credentials

## Setup

1. **Clone the repository**
   ```bash
   git clone git@github.com:resume-improver/backend.git
   cd backend
   ```

2. **Install Poetry** (if not already installed)
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   # or
   sudo apt install python3-poetry
   ```
   You may need to restart your terminal or add Poetry to your PATH:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

3. **Install dependencies**
   ```bash
   poetry install
   # or
   poetry install --no-root
   ```

4. **Configure environment variables**
   - Create a `.env` file in the project root with your Yandex Cloud credentials:
     ```
     YANDEX_FOLDER_ID=your_yandex_folder_id
     YANDEX_API_KEY=your_yandex_api_key
     ```

## Running the Server

To run the FastAPI server on all network interfaces (so it's accessible from other machines):

```bash
poetry run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- The API will be available at `http://<server-ip>:8000`.
- `--reload` is for development (auto-reloads on code changes). Remove it for production.

## API Endpoint

### `POST /analyze`
Analyze a resume and generate a cover letter draft.

**Request JSON:**
```
{
  "resume_text": "...",
  "vacancy_text": "..."
}
```

**Response JSON:**
```
{
  "resume_improvements": { ... },
  "cover_letter_draft": "..."
}
```

## Notes
- Do **not** commit your `.env` file to version control.
- For production, review and restrict CORS origins in `main.py`.
