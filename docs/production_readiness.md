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
- Do not log raw CV text, audio payloads, or access tokens.

## Operations

- Use `GET /v1/ops/readiness` for readiness checks.
- Use `GET /v1/ops/metrics` with admin auth for operational counters.
- Use `GET /v1/admin/*` endpoints to inspect users, CV scans, interviews, crawler runs, and jobs.
- Back up Postgres and object/file storage regularly.
- Monitor failed CV scans, failed crawl runs, interview failures, and missing Gemini API keys.

## Known MVP limitations

- Database migrations are not yet implemented; production should add Alembic before schema changes after launch.
- Long-running work is still synchronous; production should move CV scan, evaluation, crawling, and embedding into a worker queue.
- Local file storage is acceptable for demo only; production should use S3-compatible object storage.
- The crawler has a robots.txt guard but should be replaced with official APIs, feeds, or partner integrations where possible.
- Matching quality needs offline evaluation and feedback-based tuning.

## Recommended next engineering work

- Add Alembic migrations.
- Add worker queue and scheduler.
- Add centralized logs, metrics scraping, and error tracking.
- Add object storage with signed URLs.
- Add prompt/model version registry.
- Add automated integration tests for the full CV -> interview -> match flow.
