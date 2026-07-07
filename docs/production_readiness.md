# Backend Docker Handoff Checklist

This document defines what the backend repository provides for deployment handoff, and what remains owned by the deployment/operator team.

The backend scope is to provide working application containers, environment variables, migrations, API contracts, and health/metrics surfaces. Production infrastructure decisions are outside this repository's responsibility.

## Ownership split

Backend owner:

- Maintains `Dockerfile` and `docker-compose.yml`.
- Maintains `.env.example` as the environment contract.
- Maintains Alembic migrations.
- Maintains API docs and OpenAPI contract.
- Maintains readiness/liveness/metrics endpoints.

Deployment owner:

- Chooses hosting platform.
- Injects production secrets.
- Configures HTTPS, domain, DNS, reverse proxy, and ingress.
- Configures persistent volumes or managed Postgres/Redis/MinIO.
- Configures backups and restore procedures.
- Configures monitoring, alerting, log shipping, and incident response.
- Decides scaling and resource limits.

## Required environment

- Set `GEMINI_API_KEY` for real CV scan, interview evaluation, and Gemini Live interview.
- Set database, Redis, MinIO, and Celery variables through `.env` or production secret management.
- Run `alembic upgrade head` before serving traffic.
- Do not bake secrets into images.

## Data and privacy

- Require user login before CV upload, interview, and matching.
- Require `consent_accepted=true` before CV scan.
- Keep CV draft/final versions for auditability.
- Use `DELETE /v1/privacy/me/data` to support account data deletion.
- Use `GET /v1/privacy/me/export` to support user data export.
- Do not log raw CV text, audio payloads, or access tokens.

## Operations

- Use `GET /v1/ops/readiness` for readiness checks.
- Use `GET /v1/ops/liveness` for lightweight liveness checks.
- Use `GET /v1/ops/metrics` with admin auth for operational counters.
- Scrape `/metrics` with Prometheus when `PROMETHEUS_ENABLED=true`.
- Use `GET /v1/admin/*` endpoints to inspect users, CV scans, interviews, crawler runs, and jobs.
- Backups are deployment-owner responsibility, but must cover Postgres and MinIO data.
- Monitor failed CV scans, failed crawl runs, interview failures, and missing Gemini API keys.
- Monitor failed model runs and prompt/model versions through admin APIs.
- Monitor audit logs for admin and privacy-sensitive actions.

## Known MVP limitations

- Database migrations use Alembic. New schema changes must be shipped through explicit revisions.
- Long-running work is still synchronous; production should move CV scan, evaluation, crawling, and embedding into a worker queue.
- Local file storage is acceptable for development only; production deployment should use persistent MinIO or a deployment-team-approved object storage service.
- The crawler has a robots.txt guard but should be replaced with official APIs, feeds, or partner integrations where possible.
- Matching quality needs offline evaluation and feedback-based tuning.

## Recommended next engineering work

- Add worker queue and scheduler.
- Add centralized logs, metrics scraping, and error tracking.
- Add object storage with signed URLs.
- Add prompt/model version registry.
- Add automated integration tests for the full CV -> interview -> match flow.
