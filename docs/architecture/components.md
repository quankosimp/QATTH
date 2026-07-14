# Architecture Components

## 1. Component map

| Component | Trách nhiệm | Không chịu trách nhiệm |
|---|---|---|
| Edge/CDN/WAF | TLS, static delivery, request filtering, coarse rate policy | Business authorization, credit, canonical data |
| API service | AuthZ, validation, REST/SSE, orchestration nhanh, signed URL, realtime control | Batch extraction/crawl dài, lưu blob local |
| Realtime interview gateway | Session token, Gemini Live relay, event sequencing, reconnect | Final evaluation, canonical CV |
| Worker services | AI jobs, verification, indexing, export, reconciliation | Client session/UI |
| PostgreSQL + pgvector | Transactional state, history, FTS/vector retrieval, outbox/audit | PDF/audio blob, ephemeral cache |
| Redis | Rate limit, cache, lock, ephemeral coordination, queue backend tùy chọn | Source of truth cho billing/CV |
| R2 | Private immutable-ish blob/artifact | Business query, authorization decision |
| OpenAI adapter | Structured extraction, evaluation, embedding, web search, explanation | Canonical truth, job-active truth |
| Gemini Live adapter | Realtime audio conversation | Billing ledger, final persisted evaluation |
| Payment adapter | Checkout/customer/portal mapping, webhook normalization | Card storage, entitlement truth ngoài transaction nội bộ |
| Observability | Metrics, logs, traces, alert routing | Business record/audit replacement |

## 2. API service

Module logic đề xuất:

- <code>identity</code>: OIDC claims mapping, user/session/scope.
- <code>profiles</code>: candidate profile và preferences.
- <code>files</code>: upload intent, completion, signed download.
- <code>cv</code>: scan/draft/confirm/version/analysis.
- <code>interviews</code>: plan, session state, realtime credential, report.
- <code>jobs</code>: indexed query, detail, interaction/application.
- <code>discovery</code>: live search run, SSE event và orchestration.
- <code>recommendations</code>: candidate snapshot, match run/result.
- <code>billing</code>: catalog, entitlement, reservation, ledger, webhook.
- <code>privacy</code>: export/deletion/consent.
- <code>admin</code> và <code>ops</code>: privileged workflow, health, job controls.

API phải stateless giữa request. Sticky session chỉ có thể là tối ưu realtime, không phải điều kiện correctness.

## 3. Worker và queue isolation

| Queue | Workload | Timeout/retry định hướng | Priority |
|---|---|---|---|
| ai-cv | PDF extraction, schema repair, CV analysis | 60-120s, retry provider transient có giới hạn | Medium |
| ai-interview | Transcript evaluation/report | 60-180s, idempotent theo evaluation ID | High |
| discovery | OpenAI web search, fetch/verify/normalize | 15-60s từng stage, partial completion | Medium |
| indexing | FTS document, embedding, dedup/reindex | Batch, retry an toàn | Low |
| privacy | Export/deletion | Dài, checkpoint, audit chặt | High |
| billing | Webhook, settlement, reconciliation | Ngắn, strict idempotency | Critical |
| maintenance | Retention, stale jobs, outbox | Scheduled, observable | Low |

Không để job indexing lớn chiếm worker slot hoặc DB pool của billing/realtime. Queue depth và oldest-message age là capacity signal bắt buộc.

## 4. PostgreSQL

PostgreSQL giữ invariant bằng:

- Foreign key và unique constraint.
- Check constraint cho state/amount khi phù hợp.
- Transaction cho confirm CV, reserve credit, settle webhook.
- Partial/composite index theo access pattern.
- GIN cho FTS/JSONB query được kiểm soát.
- HNSW hoặc IVFFlat cho pgvector sau khi benchmark dataset thực.
- Advisory lock chỉ khi unique/state transition chưa đủ; tránh lock dài.
- Row-level security có thể đánh giá thêm nhưng không thay thế service authorization.

Connection pool phải được budget theo tổng instance/worker, không theo riêng từng process.

## 5. Redis

Redis dùng cho dữ liệu có thể tái tạo hoặc ngắn hạn:

- Distributed rate limit token bucket/sliding window.
- Idempotency response cache ngắn hạn khi record bền chưa cần.
- Realtime connection/session coordination.
- Cache job detail/search có version key và TTL.
- Distributed lock ngắn cho singleton/reconciliation.
- Queue broker/result backend nếu framework chọn Redis.

Credit balance, subscription state, CV draft và audit không chỉ tồn tại trong Redis.

## 6. R2 object storage

Object key do server sinh, ví dụ theo opaque user/resource UUID, không chứa email hoặc tên thật. Metadata tối thiểu trong database:

- owner/resource.
- bucket/key.
- content type và size.
- SHA-256 checksum.
- upload/security status.
- created/retention/deleted timestamps.
- encryption/version identifier nếu provider cung cấp.

Upload flow dùng signed PUT hoặc multipart intent. Download dùng signed GET ngắn hạn. Worker chỉ đọc object sau complete validation.

## 7. OpenAI adapter

Interface nghiệp vụ đề xuất:

- <code>extract_cv(file_ref, schema_version)</code>
- <code>analyze_cv(cv_version, rubric_version)</code>
- <code>evaluate_interview(transcript_ref, rubric_version)</code>
- <code>embed_documents(items, embedding_version)</code>
- <code>search_jobs(query, constraints)</code>
- <code>explain_matches(candidate_snapshot, jobs)</code>

Adapter chịu trách nhiệm timeout/retry, request ID, structured schema validation, token/cost accounting, redaction và provider error mapping. Domain service quyết định state transition, authorization và dữ liệu nào được canonicalize.

Model/prompt version không được activate chỉ bằng thao tác admin: backend yêu cầu immutable eval report có dataset checksum, sample count và metric đạt fixed policy threshold. Rollout dưới 100% giữ active baseline và chọn canary deterministically theo correlation subject; promote/rollback là activate version đã có evidence.

Web search output là discovery candidate. URL verification/parser độc lập phải quyết định freshness và normalized fields.

## 8. Gemini Live adapter

Gateway quản lý:

- Tạo provider session với system instruction đã version.
- Audio format negotiation và backpressure.
- Mapping client event sang provider event.
- Sequence, heartbeat, timeout và reconnect token.
- Persist transcript/event tối thiểu cần thiết.
- Kết thúc provider session và enqueue evaluation.

Không log raw audio/event tùy tiện. Nếu lưu audio, cần consent, retention và object metadata riêng.

## 9. Retrieval và ranking

Pipeline Product v1:

1. Hard filters từ preference/compliance.
2. PostgreSQL FTS lấy lexical candidates.
3. pgvector lấy semantic candidates.
4. Fusion bằng Reciprocal Rank Fusion hoặc weighted normalized score.
5. Freshness/source quality adjustment.
6. Reranker trên top-K với versioned feature set.
7. LLM explanation chỉ cho top-N nhỏ.

Ranking service lưu score breakdown đủ cho offline evaluation nhưng API chỉ trả phần giải thích an toàn cho user. Không để LLM trực tiếp search toàn bộ database hoặc tự quyết định hard filter.

## 10. Billing component

- Plan catalog và price version.
- Subscription projection từ verified webhook.
- Credit account và append-only ledger.
- Usage reservation trước AI/realtime action.
- Settlement/release sau outcome.
- Webhook inbox unique và raw payload retention.
- Reconciliation scheduled giữa reservation, provider usage và payment events.

Payment provider là transport/source event; entitlement có hiệu lực trong QATTH phải được materialize transactionally.

## 11. Privacy component

Deletion workflow dùng saga/checkpoint:

1. Revoke access/session.
2. Mark account pending deletion.
3. Stop new processing.
4. Delete/anonymize domain rows theo policy.
5. Delete R2 objects và cache.
6. Ghi tombstone/audit tối thiểu hợp pháp.
7. Chờ backup expiry hoặc ghi exception.
8. Hoàn tất và thông báo.

Export tạo snapshot, đóng gói artifact, signed URL TTL và tự xóa theo retention.

## 12. Operations component

- Liveness: process/event loop hoạt động.
- Readiness: DB và runtime migration compatible; dependency bắt buộc khỏe.
- Startup: validate config, initialize telemetry, không tự chạy schema mutation.
- Shutdown: ngừng nhận traffic, drain request, close realtime có kiểm soát, worker hoàn tất/return job.
- Metrics/log/trace theo NFR: FastAPI, SQLAlchemy và Celery phát W3C-context spans qua OTLP; provider adapter tạo span an toàn không chứa CV, transcript, email, credential hoặc full query.
- Admin retry/adjustment luôn có actor, reason và audit.
