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
