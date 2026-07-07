# API Contract Summary

Base URL: `http://localhost:8000`

All REST endpoints return:

```json
{
  "data": {},
  "error": null,
  "meta": {
    "request_id": "uuid",
    "version": "v1"
  }
}
```

## CV

- `GET /v1/cvs`
- Returns CVs owned by the authenticated user, including latest version number.

- `POST /v1/cvs/scan`
- Multipart form fields:
- `file`: PDF or DOCX
- `target_role`: optional string
- `language`: `vi` or `en`
- `consent_accepted`: must be `true`
- Returns `cv_id`, status `pending_review`, and `draft_profile`.
- The scan result is not saved as the final `profile` until the user confirms edited JSON.

- `PUT /v1/cvs/{cv_id}/profile`
- Body: edited `CVProfile` JSON.
- Saves the reviewed profile to the database and changes status to `completed`.
- Creates a new `final` CV version.

- `GET /v1/cvs/{cv_id}/versions`
- Returns LLM draft and user-reviewed profile versions.

- `GET /v1/cvs/{cv_id}`
- Returns `draft_profile` when pending review and `profile` after completion.

## Interviews

- `POST /v1/interviews`
- Body:

```json
{
  "cv_id": "uuid",
  "target_role": "Backend Developer Intern",
  "language": "vi"
}
```

- `WS /v1/interviews/{interview_id}/stream`
- Client events:

```json
{"type": "text.message", "payload": {"text": "candidate answer"}}
{"type": "audio.chunk", "payload": {"mime": "audio/pcm", "sample_rate": 16000, "data_base64": "..."}}
{"type": "control.end_turn", "payload": {}}
{"type": "control.end", "payload": {}}
```

- Server events:

```json
{"type": "interview.state", "payload": {"state": "live"}}
{"type": "transcript.user", "payload": {"text": "...", "final": true}}
{"type": "transcript.model", "payload": {"text": "...", "final": true}}
{"type": "error", "payload": {"code": "ERROR_CODE", "message": "..."}}
```

- `POST /v1/interviews/{interview_id}/end`
- Ends the interview and returns structured evaluation.

- `GET /v1/interviews/{interview_id}/result`
- Returns status, transcript, and evaluation if available.

## Jobs

- `POST /v1/jobs/crawl-runs`
- Body:

```json
{
  "source": "seed",
  "query": "it",
  "max_pages": 1
}
```

- Supported sources: `seed`, `itviec`.
- `seed` is deterministic for local demo.
- `itviec` attempts public crawling with robots.txt guard.

- `GET /v1/jobs?q=backend&skill=python&level=internship`
- Lists stored jobs.

- `GET /v1/jobs/{job_id}`
- Returns JD and source URL.

## Matches

- `POST /v1/matches`
- Body:

```json
{
  "cv_id": "uuid",
  "interview_id": "uuid-or-null",
  "limit": 10,
  "location": null,
  "working_model": null
}
```

- Returns ranked jobs, scores, fit reasons, gap reasons, CV/interview evidence, and apply URL.

- `GET /v1/matches/{match_id}`
- Reloads a previous match run.

## Preferences, feedback, privacy

- `GET /v1/preferences/jobs`
- Returns authenticated user's job search preferences.

- `PUT /v1/preferences/jobs`
- Saves target roles, locations, working models, salary expectation, and preferred skills.

- `POST /v1/jobs/{job_id}/interactions`
- Records `saved`, `applied`, `relevant`, `not_relevant`, or `hidden` job feedback.

- `GET /v1/jobs/interactions`
- Lists user's job interactions.

- `POST /v1/privacy/consents`
- Records consent decisions.

- `GET /v1/privacy/consents`
- Lists consent history.

- `DELETE /v1/privacy/me/data`
- Deletes user-owned CVs, interviews, matches, interactions, consents, tokens, and deactivates the account.

## Admin

Admin endpoints require an authenticated user with role `admin`.

- `GET /v1/admin/overview`
- Returns operational counts for users, CVs, interviews, jobs, and failed crawl runs.

- `GET /v1/admin/users`
- Lists users.

- `PATCH /v1/admin/users/{user_id}/status`
- Activates or deactivates a user.

- `GET /v1/admin/cv-scans`
- Lists CV scan status and failures.

- `GET /v1/admin/interviews`
- Lists interview sessions.

- `GET /v1/admin/crawl-runs`
- Lists crawler runs and failures.

- `GET /v1/admin/jobs`
- Lists stored jobs.

## Ops

- `GET /v1/ops/readiness`
- Returns database, storage directory, and Gemini configuration readiness.

- `GET /v1/ops/metrics`
- Admin-only operational counters mirroring the admin overview.

## Background tasks

- `POST /v1/tasks`
- Enqueues a background task. Initial supported type is `noop`; production task types are wired incrementally.

- `GET /v1/tasks`
- Lists tasks for the current user, or all tasks for admin users.

- `GET /v1/tasks/{task_id}`
- Returns task status, attempts, result payload, and error payload.

- `POST /v1/tasks/{task_id}/retry`
- Retries a failed/completed task when attempts remain.

## Files

- `GET /v1/files/{file_id}`
- Returns file asset metadata for a user-owned or admin-accessible file.

- `GET /v1/files/{file_id}/signed-url`
- Returns a short-lived URL for downloading the object from S3-compatible storage. In local fallback mode, the URL is the local storage key.
