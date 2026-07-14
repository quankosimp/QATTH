FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system qatth \
    && adduser --system --ingroup qatth qatth

COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY migrations ./migrations

RUN pip install --upgrade pip \
    && pip install -e . \
    && mkdir -p /app/data/uploads /app/data/generated \
    && chown -R qatth:qatth /app/data

USER qatth

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
