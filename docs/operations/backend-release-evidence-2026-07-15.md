# Backend Release Evidence - 2026-07-15

## 1. Kết luận

Backend Product v1 ở trạng thái **code-ready for integration acceptance**, chưa phải production release approval. Record này xác nhận source code, API contract, migration head và Docker Compose contract tại local; không thay thế provider staging, managed infrastructure, load, security hoặc restore evidence.

| Thuộc tính | Giá trị |
|---|---|
| Validated code commit | <code>860611b</code> |
| Branch | <code>feature/product-v1-backend</code> |
| Database head | <code>20260715_0034</code> |
| Runtime | Python 3.12, local validation environment |
| Provider credentials | Không dùng trong offline suite |
| Validation date | 2026-07-15, Asia/Bangkok |

Evidence-only commit chứa file này không thay đổi runtime đã validation.

## 2. Automated validation

| Contract | Command | Result |
|---|---|---|
| Unit/contract/integration tests | <code>PYTHONPATH=backend .venv/bin/pytest -q</code> | 121 passed, không warning |
| Static analysis | <code>.venv/bin/ruff check backend tests scripts</code> | Passed |
| OpenAPI drift | <code>PYTHONPATH=backend .venv/bin/python scripts/sync_openapi.py --check</code> | Synchronized |
| Migration topology | <code>.venv/bin/alembic heads</code> | Một head: <code>20260715_0034</code> |
| Python dependency consistency | <code>.venv/bin/pip check</code> | No broken requirements |
| Container orchestration syntax | <code>docker compose config</code> với <code>.env.example</code> thay cho local <code>.env</code> | Valid |

## 3. Backend capabilities covered

- OIDC/session/account boundary, ownership/scope, consent và distributed rate limit.
- Secure file lifecycle, PDF/hash/malware validation, CV draft-confirm/version/analysis lineage.
- Interview token/event/report lifecycle, concurrency guards, reconnect boundary và Gemini adapter tests.
- Job ingest/provenance, OpenAI live-discovery adapter, PostgreSQL FTS/pgvector ranking, recommendation và application history.
- Versioned billing catalog, trial/buckets, immutable ledger, reservation/reconciliation, Paddle adapter và dual control.
- Privacy export/deletion/retention, immutable audit, admin operations, durable dispatch/leases và safe errors.
- Prometheus metrics, structured logs, W3C/OTLP tracing và quality-gated model canary/rollback.

## 4. Release evidence còn bắt buộc

| Gate | Owner chính | Evidence cần nộp |
|---|---|---|
| OIDC, R2, PostgreSQL, Redis, ClamAV | Deployment + backend | Staging integration report và failure-path evidence |
| Gemini Live | Backend + deployment | Voice fixture, reconnect/backpressure, 20 concurrent sessions, latency/transcript-loss report |
| OpenAI job discovery | Backend/product | Reviewed Internet sources, citation/active-job quality report và provider usage/cost |
| Model quality | Product/AI | Versioned Vietnamese/English CV and interview datasets, expert annotations, threshold report per model/prompt version |
| Paddle | Billing owner | Sandbox checkout/portal/webhook/replay/reconciliation certification |
| Performance | Backend + deployment | k6 REST/SSE plus async/voice stress and soak reports against NFR percentiles |
| Data recovery | Deployment + backend | Production-sized migration rehearsal, managed backup policy và restore/RPO/RTO report |
| Security | Security + deployment + backend | Dependency/image scan, threat review, TLS/secret/R2 policy evidence và log/trace redaction test |
| Observability platform | Deployment | OTLP collector acceptance, dashboard, SLO/error-budget alerts và runbook links |

## 5. Release decision rule

Không chuyển các dòng <code>Partial</code> hoặc <code>Evidence pending</code> trong traceability sang <code>Implemented/Accepted</code> chỉ dựa trên local test. Release owner phải liên kết artifact cho từng gate ở mục 4, ghi unresolved risk có owner/expiry và xác nhận commit/image digest trùng code được kiểm thử.
