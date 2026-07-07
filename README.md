# QATTH Career Platform

Backend-first MVP for IT students:

- Scan CV into structured data.
- Run a Gemini Live virtual interview.
- Evaluate interview performance.
- Match the student to IT jobs and show job descriptions.
- Expose a stable OpenAPI contract for frontend integration.
- Provide a temporary Streamlit local demo.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --app-dir backend
```

API docs:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Optional Postgres + pgvector

```bash
docker compose up -d postgres
```

Then set:

```env
DATABASE_URL=postgresql+psycopg://qatth:qatth@localhost:5432/qatth
```

## Development rule

This repo is implemented in incremental parts. Each major product part should be committed before starting the next one.
