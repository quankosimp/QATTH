# QATTH Career Platform

Backend-first MVP for IT students:

- Scan CV into structured data.
- Run a Gemini Live virtual interview.
- Evaluate interview performance.
- Match the student to IT jobs and show job descriptions.
- Expose a stable OpenAPI contract for frontend integration.

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

## Docker Compose deployment

Create `.env` first:

```bash
cp .env.example .env
```

Run the full local deployment:

```bash
docker compose up --build
```

Services:

- FastAPI: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- PostgreSQL + pgvector: `localhost:5432`

For Gemini-backed CV scan and Live interview, set `GEMINI_API_KEY` in `.env` before starting Compose.

## Temporary demo branch

The Streamlit demo client is intentionally kept outside this backend/product branch. Use branch `agent/qatth-streamlit-demo` for temporary local feature testing with Streamlit.

## Development rule

This repo is implemented in incremental parts. Each major product part should be committed before starting the next one.

## API contract

See `docs/api_contract.md` for the frontend-facing REST/WebSocket contract summary.

## Production readiness

See `docs/production_readiness.md` for required operational, privacy, and deployment checks before using real student data.
