# QATTH Career Platform

QATTH is a career-assistant platform for IT students who need a clearer path from **CV preparation** to **interview practice** to **finding suitable jobs**.

The product is designed for students at internship, fresher, and junior level. Instead of only showing a job board, QATTH analyzes the student's CV, helps them practice through an AI interview, evaluates their readiness, and recommends jobs with clear reasons and skill gaps.

This repository is the **backend/product API branch**. It exposes the API contract for a separate frontend team or future frontend application.

## What the product does

QATTH helps an IT student answer three practical questions:

1. Is my CV understandable and structured enough for job matching?
2. Am I ready for interviews for my target IT role?
3. Which jobs fit my current skills, projects, preferences, and interview performance?

Main user journey:

1. The student creates an account.
2. The student uploads a CV.
3. The system uses an LLM to scan the CV into structured JSON.
4. The student reviews and edits the scanned JSON before saving it.
5. The student starts either a mock interview for a target role or a diagnostic interview when they are not sure which JD fits.
6. The system evaluates the interview using a role-based rubric.
7. The system can create a candidate discovery profile from the reviewed CV and diagnostic interview.
8. The system searches suitable live JD sources, ranks jobs, and explains fit/gaps.
9. The student can save jobs, mark applied jobs, and give feedback so future matching can improve.

## Core capabilities

### CV scan and review

- Upload PDF or DOCX CV.
- Scan CV into structured JSON using Gemini.
- Keep the LLM result as a draft.
- Let the user edit the JSON before saving.
- Store CV versions so draft and final profiles can be audited.

### Virtual interview

- Create an interview room from a reviewed CV.
- Support WebSocket-based interview sessions.
- Integrate with Gemini Live when `GEMINI_API_KEY` is configured.
- Store transcript and evaluation results.
- Return interview score, strengths, weaknesses, recommended roles, and skill gaps.

### Job ingestion, discovery, and matching

- Store IT job postings with JD text, source URL, company, level, skills, location, and working model.
- Seed local demo jobs for testing.
- Support crawler adapter structure for public job sources.
- Create candidate discovery profiles from reviewed CVs and diagnostic interviews.
- Search live JD sources through a configured Search API provider.
- Rank jobs using CV profile, discovery profile, interview result, user preferences, skill overlap, and semantic similarity.
- Return match score, fit reasons, gap reasons, and apply URL.

### User product loop

- User registration and login.
- User ownership for CVs, interviews, and match results.
- Job preferences: target roles, locations, working models, salary expectation, preferred skills.
- Job interactions: saved, applied, relevant, not relevant, hidden.
- Privacy controls and user data deletion endpoint.

### Admin and operations

- Admin role support.
- Admin APIs for users, CV scans, interviews, crawler runs, and jobs.
- Readiness endpoint for runtime health checks.
- Admin metrics endpoint for operational counters.
- Production readiness checklist in `docs/production_readiness.md`.

## Current repository scope

This branch focuses on the backend and API contract.

Included:

- FastAPI backend
- SQLAlchemy models
- Auth and ownership
- CV scan/review/versioning
- Interview APIs and WebSocket contract
- Gemini adapters
- Job ingestion and matching
- Admin APIs
- Privacy and feedback APIs
- Docker Compose for API + Postgres
- API documentation via OpenAPI

Not included in this branch:

- Production frontend application
- Temporary Streamlit demo

The temporary Streamlit demo lives on branch:

```text
agent/qatth-streamlit-demo
```

## API documentation

After starting the backend:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

Frontend-facing contract summary:

```text
docs/api_contract.md
```

## Local development

Requirements:

- Python 3.11+
- Docker, optional but recommended
- Gemini API key, optional for demo fallback but required for real AI behavior

Run locally with SQLite:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --app-dir backend
```

Run backend stack with Docker Compose:

```bash
cp .env.example .env
docker compose up --build
```

Services:

- FastAPI: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Prometheus metrics: `http://localhost:8000/metrics`
- PostgreSQL + pgvector: `localhost:5432`
- Redis: `localhost:6379`
- MinIO object storage: `http://localhost:9001`
- Celery worker: `worker` service in Docker Compose

For real Gemini-backed CV scan, interview evaluation, discovery profile generation, and Gemini Live interview, set this in `.env`:

```env
GEMINI_API_KEY=your_key_here
```

For live external JD recommendations via SerpApi Google Jobs, set:

```env
JOB_SEARCH_PROVIDER=serpapi_google_jobs
SERPAPI_API_KEY=your_key_here
JOB_SEARCH_DEFAULT_LOCATION=Vietnam
```

Database migrations:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

## Typical backend flow

1. Register or login:

```text
POST /v1/auth/register
POST /v1/auth/login
```

2. Scan CV as draft:

```text
POST /v1/cvs/scan
```

3. Save reviewed CV JSON:

```text
PUT /v1/cvs/{cv_id}/profile
```

4. Create and run interview. Use `interview_type=mock` for JD-first practice or `interview_type=diagnostic` when the student is unsure which JD fits:

```text
POST /v1/interviews
WS   /v1/interviews/{interview_id}/stream
POST /v1/interviews/{interview_id}/end
```

5. Candidate-first discovery flow:

```text
POST /v1/discovery-profiles
POST /v1/recommendations/jobs
```

6. Seed or ingest jobs:

```text
POST /v1/jobs/crawl-runs
```

7. Generate JD-first job matches:

```text
POST /v1/matches
```

8. Record product feedback:

```text
POST /v1/jobs/{job_id}/interactions
```

## Product status

This is an MVP foundation for a real product. It is intentionally backend-first so a dedicated frontend can be built later with a proper web framework.

Important remaining production work:

- Wire concrete CV scan, interview evaluation, job crawl, and match generation jobs into the Celery task system.
- Improve crawler sources through official APIs, feeds, or partnerships.
- Add automated integration tests for the full CV to interview to job matching flow.
- Add production email delivery for password reset instead of returning local/dev reset tokens.
