# Production Readiness Checklist

This repository is now beyond a single-user demo, but it is still an MVP. Use this checklist before running with real student data.

## Required environment

- Set `GEMINI_API_KEY` for real CV scan, interview evaluation, and Gemini Live interview.
- Use Postgres in Docker Compose or managed Postgres in production.
- Keep API keys only in server-side environment variables.
- Run the API behind HTTPS.

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
- Back up Postgres and object/file storage regularly.
- Monitor failed CV scans, failed crawl runs, interview failures, and missing Gemini API keys.
- Monitor failed model runs and prompt/model versions through admin APIs.
- Monitor audit logs for admin and privacy-sensitive actions.

## Known MVP limitations

- Database migrations use Alembic. New schema changes must be shipped through explicit revisions.
- Long-running work is still synchronous; production should move CV scan, evaluation, crawling, and embedding into a worker queue.
- Local file storage is acceptable for demo only; production should use managed MinIO object storage.
- The crawler has a robots.txt guard but should be replaced with official APIs, feeds, or partner integrations where possible.
- Matching quality needs offline evaluation and feedback-based tuning.

## Recommended next engineering work

- Add worker queue and scheduler.
- Add centralized logs, metrics scraping, and error tracking.
- Add object storage with signed URLs.
- Add prompt/model version registry.
- Add automated integration tests for the full CV -> interview -> match flow.
