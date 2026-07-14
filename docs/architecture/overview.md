# Architecture Overview

## 1. Mục tiêu

Kiến trúc Product v1 phục vụ ba năng lực chính:

1. Chuyển CV PDF thành hồ sơ JSON có người dùng kiểm soát.
2. Tổ chức phỏng vấn giọng nói realtime và đánh giá có evidence.
3. Tìm, xác minh và xếp hạng job từ chỉ mục nội bộ lẫn Internet.

Thiết kế ưu tiên correctness, privacy, traceability và khả năng vận hành lâu dài hơn tốc độ làm demo.

## 2. Architecture principles

- **PostgreSQL là system of record:** business invariant nằm trong transaction, constraint và immutable history.
- **Object storage cho blob:** PDF, raw JD và export artifact không nằm trực tiếp trong database.
- **Async by default cho tác vụ dài:** CV scan, evaluation, web verification, embedding và export trả resource trạng thái.
- **Provider behind ports/adapters:** domain không phụ thuộc SDK OpenAI, Gemini hay payment cụ thể.
- **Human confirmation trước canonical CV:** AI chỉ tạo draft.
- **Evidence before explanation:** retrieval/ranking chạy bằng dữ liệu có nguồn; LLM chỉ diễn giải top results.
- **Idempotency at every external boundary:** queue, webhook, payment và operation tốn credit chịu được retry.
- **Observable state machine:** resource dài hạn có state rõ, attempt/history và correlation ID.
- **Edge không phải application database:** Cloudflare bảo vệ/phân phối; dữ liệu nghiệp vụ nằm tại managed PostgreSQL.

## 3. System context

~~~mermaid
flowchart TB
    Candidate[Candidate]
    Admin[Admin / Support]
    Client[Product Frontend]
    Edge[Cloudflare CDN / WAF]
    API[QATTH API]
    Worker[QATTH Workers]
    PG[(Managed PostgreSQL + pgvector)]
    Redis[(Managed Redis)]
    R2[(Cloudflare R2)]
    OpenAI[OpenAI API]
    Gemini[Gemini Live API]
    JobWeb[Job websites / search index]
    Payment[Payment provider]
    Obs[Observability platform]

    Candidate --> Client
    Admin --> Client
    Client --> Edge --> API
    API --> PG
    API --> Redis
    API --> R2
    API --> Worker
    Worker --> PG
    Worker --> Redis
    Worker --> R2
    API --> OpenAI
    Worker --> OpenAI
    API <--> Gemini
    OpenAI --> JobWeb
    Worker --> JobWeb
    API --> Payment
    Payment --> API
    API --> Obs
    Worker --> Obs
~~~

## 4. Runtime topology

### Edge layer

Cloudflare Pages/CDN phân phối frontend; WAF, TLS, basic bot protection và request size/rate policy nằm trước API. R2 cung cấp object storage và signed upload/download.

### Application layer

API container stateless xử lý authentication, authorization, validation, orchestration nhanh, REST/SSE và realtime gateway. Worker container xử lý queue tách theo workload:

- <code>realtime-control</code>: control event cần độ trễ thấp, không chạy batch nặng.
- <code>ai</code>: CV extraction, interview evaluation, explanation.
- <code>discovery</code>: web search, URL verification, normalization.
- <code>indexing</code>: FTS document, embedding, dedup/reindex.
- <code>maintenance</code>: retention, export, reconciliation, outbox.

Một implementation có thể dùng nhiều process hoặc service; queue semantics mới là contract, không khóa vào Celery.

### Data layer

- PostgreSQL + pgvector: identity mapping, CV versions, interview metadata/events, jobs, ranking, billing, audit/outbox.
- Redis: cache ngắn hạn, distributed rate limit, lock/coordination, ephemeral session state và queue backend nếu chọn.
- R2: PDF, raw source snapshot, audio/transcript artifact lớn, report/export artifact.

### Provider layer

- OpenAI: structured extraction, embeddings, interview evaluation, web search, rerank support và explanation.
- Gemini Live: voice interview realtime.
- OIDC provider: identity proof; authorization vẫn do QATTH quyết định.
- Payment adapter: checkout, subscription và webhook.
- Job source: website/search result; mọi dữ liệu phải giữ provenance và tuân thủ quyền truy cập.

## 5. Trust boundaries

| Boundary | Risk chính | Control |
|---|---|---|
| Client to Edge/API | Token theft, abuse, oversized upload | TLS, OIDC, WAF, distributed rate limit, signed upload, schema validation |
| API to object storage | Object key spoofing, data leak | Server-generated key, ownership, short TTL, checksum, private bucket |
| API/Worker to AI provider | PII leakage, prompt injection, cost abuse | Data minimization, adapter policy, structured output validation, budget/quota, redaction |
| Internet job content to system | Malicious HTML, stale/fake JD, prompt injection | Safe fetch/parser, URL policy, provenance, content isolation, verification |
| Payment webhook to API | Forgery, replay, duplicate credit | Signature/timestamp, inbox uniqueness, idempotent transaction |
| Admin to production data | Privilege misuse | RBAC/scope, masking, audit, least privilege, break-glass process |
| Queue delivery to worker | Duplicate/out-of-order event | Idempotency key, state transition guard, transactional outbox/inbox |

## 6. Core state machines

### CV scan

<code>queued -> extracting -> draft_ready -> confirmed</code>

Failure branches: <code>validation_failed</code>, <code>extraction_failed</code>, <code>cancelled</code>. Confirm tạo CV version mới; không đổi scan artifact thành canonical record tại chỗ.

### Interview

<code>created -> ready -> live -> ending -> evaluating -> completed</code>

Failure branches: <code>interrupted</code>, <code>cancelled</code>, <code>evaluation_failed</code>. Transcript event đã persist không bị xóa khi evaluation retry.

### Job search run

<code>queued -> searching -> verifying -> ranking -> completed</code>

Có thể phát event từng phần. Run thất bại một provider vẫn có thể hoàn tất degraded nếu còn đủ kết quả có nguồn.

### Credit usage

<code>reserved -> settled</code> hoặc <code>reserved -> released</code>. Reconciliation xử lý reservation quá hạn; ledger không mutate.

## 7. Consistency model

- Strong consistency cho ownership, CV confirm, subscription entitlement, credit reservation/settlement và state transition.
- Eventual consistency cho embedding, recommendation refresh, job verification, analytics và search index-derived fields.
- Transactional outbox nối database commit với queue/event publication.
- Idempotency record hoặc unique constraint bảo vệ client retry và provider duplicate.
- Snapshot input IDs giúp report/ranking tái lập dù profile active thay đổi.

## 8. Demo hiện tại và target

Demo hiện tại đã có nhiều domain resource trong FastAPI, background tasks, PostgreSQL/pgvector container, Redis và object storage tương thích S3. Tuy nhiên target yêu cầu refactor quan trọng:

- Authentication demo sang OIDC boundary và distributed session/revocation.
- In-process rate limit sang Redis/distributed policy.
- JSON embedding sang pgvector column/index thực.
- CV scan trực tiếp sang draft/confirm state machine rõ.
- Job crawl/search thử nghiệm sang hybrid retrieval + live web search + verification.
- AI call rời rạc sang provider adapter, model run audit, eval và cost controls.
- Schema tạo trực tiếp sang migration chain production.
- Side effect sang outbox/idempotency/reconciliation.
- MinIO local chỉ là emulator; production target dùng R2.
- Celery có thể tiếp tục hoặc thay thế, nhưng queue contract không phụ thuộc framework.

## 9. Evolution path

1. **Foundation:** migrations, OIDC, object abstraction, Redis rate limit, standard errors/idempotency, observability.
2. **CV lifecycle:** upload intent, extraction schema, editable draft, confirm/version, quality eval.
3. **Interview:** realtime gateway/Gemini Live, event persistence, evaluation/report.
4. **Discovery:** normalized job store, FTS/pgvector, OpenAI web search, verification, rerank/SSE.
5. **Commercial/operations:** subscription, credit ledger, webhook inbox, admin, privacy workflows.
6. **Hardening:** load/security/restore tests, SLO alerts, provider failover/degradation and cost tuning.

Mỗi giai đoạn phải giữ backward compatibility hoặc có migration plan; không triển khai toàn bộ bằng một refactor big-bang.
