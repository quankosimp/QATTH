# Product v1 Requirement Traceability

## 1. Mục đích và quy ước

Ma trận này nối requirement với API contract, logical entity và automated test. Mốc đánh giá: 2026-07-14.

- **Implemented:** backend path, migration/domain rule và automated contract test đã có.
- **Partial:** backend boundary đã có nhưng provider, protocol hoặc một acceptance criterion chưa được kiểm chứng end-to-end.
- **Evidence pending:** requirement chỉ có thể kết luận sau phép đo/hạ tầng production-like; unit test không phải bằng chứng SLO.
- OpenAPI operation là mapping chi tiết nhất: mỗi operation phải có <code>x-requirement-ids</code> và <code>x-implementation-status</code>.
- Entity chi tiết nằm trong [Database Schema](../database/schema.md); flow nằm trong [Data Flow](../architecture/data-flow.md).

## 2. Functional requirements

| Requirement IDs | API / entity evidence | Automated evidence | Status / gap |
|---|---|---|---|
| FR-AUTH-001..004 | auth callback, sessions, admin account status; users/auth_identities/user_sessions/audit_events | <code>test_identity_contract.py</code>, <code>test_product_admin_ops_contract.py</code> | Implemented; production OIDC configuration is environment acceptance |
| FR-PROFILE-001..003 | profile, preferences, consents; user_job_preferences/consent_records | <code>test_identity_contract.py</code>, <code>test_contract.py</code> | Implemented |
| FR-FILE-001..003 | upload intent/complete/download; file_assets | <code>test_product_cv_contract.py</code> | Implemented; production R2/malware engine evidence pending |
| FR-CV-001..009 | scans, attempts, drafts, versions, analysis, retry/archive; CV domain tables | <code>test_product_cv_contract.py</code> | Implemented |
| FR-INT-001..002, FR-INT-004..008 | interview/session token/events/report/retry/feedback; interview tables/model_runs | <code>test_product_interview_contract.py</code> | Implemented |
| FR-INT-003 | realtime WebSocket and Gemini Live adapter boundary | <code>test_product_interview_contract.py</code> and <code>test_gemini_interview_gateway.py</code> cover lifecycle, protocol, resumption and capacity; not real audio | Partial: staging voice, reconnect and backpressure acceptance required |
| FR-JOB-001, FR-JOB-003..005, FR-JOB-010..012 | sources/postings/snapshots/interactions/applications/moderation | <code>test_product_job_search_contract.py</code>, <code>test_job_search.py</code> | Implemented |
| FR-JOB-002 | live search run, OpenAI search-call/citation/full-source provenance and terminal failure | <code>test_product_job_search_contract.py</code> and <code>test_live_job_discovery.py</code> with provider fixtures | Partial until reviewed Internet sources and provider credentials are verified in staging |
| FR-JOB-006..009 | FTS/pgvector search, hard filters, rerank, explanations, run status/SSE | <code>test_product_job_search_contract.py</code>, <code>test_job_search.py</code> | Implemented; relevance/performance evidence tracked by NFR |
| FR-REC-001..004 | candidate profile, recommendation run/items and append-only attributed feedback | <code>test_product_recommendations_contract.py</code>, <code>test_recommendation_feedback_contract.py</code> | Implemented |
| FR-BILL-001, FR-BILL-004..011 | catalog, account/buckets/ledger/reservation/refund/review/approval and domain-aware timeout reconciliation | <code>test_product_billing_contract.py</code>, <code>test_credit_reservation_reconciliation.py</code> | Implemented |
| FR-BILL-002..003 | checkout/portal, Paddle adapter, webhook inbox, provider reconciliation and payload retention | <code>test_product_billing_contract.py</code>, <code>test_payment_adapter.py</code>, <code>test_payment_reconciliation_contract.py</code> cover mapping, signature/replay, normalization, retry and retention | Implemented in backend; Paddle sandbox certification remains release evidence |
| FR-PRIV-001..003 | export/deletion/consent workflows; privacy_requests | <code>test_product_privacy_contract.py</code> | Implemented; production retention/backup expiry is NFR evidence |
| FR-ADMIN-001..005 | resource/user search, model config, background job, source/moderation, credit dual-control | <code>test_product_admin_ops_contract.py</code>, <code>test_product_billing_contract.py</code> | Implemented |
| FR-OPS-001..003 | health/readiness/diagnostics, correlation, atomic Redis IP/principal/action quotas and AI-cost policy | <code>test_contract.py</code>, <code>test_provider_resilience.py</code>, <code>test_distributed_rate_limit.py</code> | Implemented; multi-instance/load evidence remains an NFR gate |

## 3. Non-functional requirements

| Requirement IDs | Implementation / evidence location | Status / release evidence required |
|---|---|---|
| NFR-AVL-001 | health endpoints and SLO definition | Evidence pending: rolling production availability |
| NFR-AVL-002..004 | health/readiness, idempotent jobs, provider timeout/retry/circuit/bulkhead | Implemented; <code>test_contract.py</code>, <code>test_provider_resilience.py</code> |
| NFR-AVL-005 | interview reconnect/state boundary and distributed lease | Partial: gateway tests pass; staging WebSocket/Gemini disconnect test required |
| NFR-PERF-001..008 | [Load Testing](../operations/load-testing.md) and k6 workload | Evidence pending: publish environment, dataset and percentile report |
| NFR-DATA-001..004 | production handoff backup/restore contract | Evidence pending: managed backup and quarterly restore rehearsal |
| NFR-DATA-005..006 | transactions/constraints, migration chain and reconciliation | Partial: migration from production-sized snapshot and provider reconciliation drill required |
| NFR-SEC-001 | config/Docker boundary | Environment pending: TLS, encryption-at-rest and secret injection evidence |
| NFR-SEC-002..004 | JWT validation, deny-by-default ownership/scope, Redis rate limits | Implemented in backend; identity/admin/provider tests |
| NFR-SEC-005..008 | file state, Paddle signature/replay verification, payment redaction/retention and security process | Partial: malware engine and release security scan evidence required; payment backend controls implemented |
| NFR-PRIV-001..004, NFR-PRIV-006 | consent, minimization/provider boundary, export/delete and admin masking/audit | Implemented in backend; privacy/identity/admin tests |
| NFR-PRIV-005 | retention workflow | Partial: scheduler and backup expiration evidence required |
| NFR-OBS-001..003, NFR-OBS-006 | correlation, Prometheus/provider metrics, structured events and audit | Implemented in backend; contract/resilience/admin tests |
| NFR-OBS-004..005 | trace/alert platform handoff | Partial/evidence pending: collector, dashboard, alert and runbook links |
| NFR-AI-001, NFR-AI-004..005, NFR-AI-007 | local schema validation, full source provenance/citation, active-page verification, top-K explanation, usage/cost budget and human CV control | Implemented; CV/job/provider tests including <code>test_live_job_discovery.py</code> |
| NFR-AI-002..003, NFR-AI-006 | model/prompt lineage exists | Partial: versioned offline evaluation datasets, thresholds and staged rollout evidence required |
| NFR-MNT-001..006 | adapters, OpenAPI sync, offline tests, production fail-fast config, this matrix and Docker image | Implemented; <code>test_openapi_contract_sync.py</code> and <code>test_production_config.py</code> guard API/config contracts |
| NFR-UX-001..002 | bilingual payload preservation and UTC/currency schemas | Implemented at API/domain boundary |
| NFR-UX-003 | persisted interview lifecycle and retryable errors | Partial until realtime fallback/reconnect acceptance passes |

## 4. Release evidence record

Mỗi release candidate phải đính kèm hoặc liên kết:

1. Commit/image digest và OpenAPI artifact đã chạy sync check.
2. Unit/contract/integration/migration test report và database revision head.
3. Load/stress/soak report có environment, dataset, concurrency, percentile và error taxonomy.
4. AI evaluation report theo model/prompt/dataset version.
5. Provider staging acceptance cho Gemini Live, web search và payment.
6. Security scan/threat review, restore rehearsal và unresolved risk có owner/expiry.

Không chuyển requirement từ Partial/Evidence pending sang Implemented chỉ bằng sửa tài liệu; phải có evidence record có thể truy lại.
