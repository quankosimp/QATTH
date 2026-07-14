# Production Runtime and Deployment Handoff

## 1. Mục đích

Tài liệu này mô tả contract mà backend phải cung cấp để deployment team triển khai QATTH Product v1. Đây không phải Terraform, tài khoản cloud hay quy trình CI/CD cụ thể.

Phân chia trách nhiệm:

- Backend team sở hữu image, process command, migration, configuration schema, health/readiness, graceful shutdown, queue semantics, telemetry instrumentation và application runbook.
- Deployment team sở hữu provision hạ tầng, account/project, DNS/TLS, network, secret injection, CI/CD, rollout/rollback, autoscaling, backup execution, monitoring platform và incident coordination.

## 2. Production target

~~~mermaid
flowchart LR
    User[User] --> CF[Cloudflare DNS/CDN/WAF]
    CF --> FE[Cloudflare Pages]
    CF --> LB[API origin / load balancer]
    LB --> API[API containers]
    LB --> RT[Realtime containers]
    API --> PG[(Managed PostgreSQL + pgvector)]
    API --> Redis[(Managed Redis)]
    API --> R2[(Cloudflare R2)]
    API --> Queue[Worker queues]
    RT --> Redis
    RT --> PG
    RT <--> Gemini[Gemini Live]
    Queue --> Worker[Worker containers]
    Worker --> PG
    Worker --> Redis
    Worker --> R2
    API --> OpenAI[OpenAI]
    Worker --> OpenAI
    API --> Payment[Payment provider]
    API --> OTel[OTel collector/platform]
    RT --> OTel
    Worker --> OTel
~~~

Cloudflare Workers/D1 không phải nơi chạy core backend hoặc system of record trong quyết định hiện tại. Cloudflare edge và R2 vẫn là thành phần chính; API/worker chạy trên nền tảng container do deployment team chọn.

## 3. Backend artifacts bắt buộc

Mỗi release backend phải cung cấp:

- OCI-compatible image được tag bằng immutable digest và release version.
- SBOM/provenance nếu pipeline hỗ trợ.
- Process command riêng cho API, realtime gateway và worker/queue.
- One-shot migration command.
- Runtime config schema và danh sách secret.
- Liveness/readiness endpoint.
- Release note và migration/rollback note.
- OpenAPI artifact tương ứng.
- Dashboard/alert/runbook requirements ở mức ứng dụng.

Image production:

- Chạy non-root.
- Không chứa secret hoặc file dữ liệu local.
- Không tự chạy migration khi mọi replica khởi động.
- Không cần writable filesystem ngoài thư mục tạm hữu hạn.
- Có signal handling và graceful shutdown.
- Pin dependency bằng lockfile.
- Tách build dependency khỏi runtime layer.
- Expose version/commit trong health hoặc telemetry, không lộ secret.

## 4. Process model

### API

Trách nhiệm REST, SSE, authorization, upload intent, business transaction và enqueue. API phải stateless; horizontal scaling không làm sai idempotency/rate limit.

Yêu cầu runtime:

- Readiness chỉ thành công khi migration version tương thích và PostgreSQL bắt buộc sẵn sàng.
- Connection pool có cấu hình theo tổng replica.
- Request body/timeouts khác nhau cho JSON, webhook và SSE.
- Không proxy PDF qua API trong flow bình thường.
- Graceful shutdown ngừng nhận request mới rồi drain trong deadline.

### Realtime gateway

Có thể cùng image nhưng nên là deployment/process pool riêng khi tải tăng.

- Hỗ trợ WebSocket upgrade và connection dài.
- Connection/session coordination qua Redis/DB, không chỉ memory.
- Giới hạn connection theo user/session và toàn hệ thống.
- Backpressure, heartbeat, idle timeout và reconnect window.
- Graceful shutdown phát event kết thúc/degraded và cho client reconnect instance khác.
- Không chạy batch worker trong cùng process pool.

### Workers

Tách concurrency/pool theo queue:

| Queue class | Ví dụ | Isolation requirement |
|---|---|---|
| Critical | billing webhook, credit settlement | Concurrency riêng, retry/idempotency chặt, alert backlog thấp |
| High | interview evaluation, privacy | Không bị indexing/crawl làm đói |
| Medium | CV extraction, live discovery | Budget provider và timeout riêng |
| Low/batch | embeddings, reindex, retention | Rate limit DB/provider, có thể pause khi incident |

Worker shutdown phải dừng lấy job mới, heartbeat job đang chạy và hoàn tất hoặc trả job về queue an toàn.

## 5. Configuration contract

Production thiếu biến bắt buộc phải fail fast. Secret được inject bởi deployment secret manager, không đặt trong file repository.

### Application

| Variable | Secret | Purpose |
|---|---:|---|
| APP_ENV | No | <code>production</code>, <code>staging</code> hoặc local |
| APP_VERSION | No | Release identifier |
| LOG_LEVEL | No | Structured log threshold |
| PUBLIC_API_ORIGIN | No | Canonical external API origin |
| ALLOWED_ORIGINS | No | Explicit CORS allowlist |
| TRUSTED_PROXY_CIDRS | No | Proxy chain accepted by application |
| REQUEST_TIMEOUT_SECONDS | No | Default bounded request timeout |

### Data services

| Variable | Secret | Purpose |
|---|---:|---|
| DATABASE_URL | Yes | PostgreSQL TLS connection string |
| DATABASE_POOL_SIZE | No | Per-process pool budget |
| DATABASE_POOL_OVERFLOW | No | Bounded overflow |
| REDIS_URL | Yes | TLS Redis connection |
| REDIS_KEY_PREFIX | No | Environment isolation |
| OBJECT_STORAGE_PROVIDER | No | Must be <code>r2</code> in target production |
| R2_ENDPOINT_URL | No | Account endpoint |
| R2_BUCKET | No | Private bucket |
| R2_ACCESS_KEY_ID | Yes | Scoped object credential |
| R2_SECRET_ACCESS_KEY | Yes | Scoped object credential |
| SIGNED_URL_TTL_SECONDS | No | Short-lived URL policy |

R2 credential phải được scope tối thiểu theo bucket/action. Frontend không nhận R2 credential; chỉ nhận signed URL.

### Identity

| Variable | Secret | Purpose |
|---|---:|---|
| OIDC_ISSUER | No | Trusted issuer |
| OIDC_AUDIENCE | No | API audience |
| OIDC_JWKS_URL | No | Optional explicit JWKS endpoint |
| OIDC_REQUIRED_CLAIMS | No | Claim policy |
| SESSION_SIGNING_KEY | Yes | Chỉ nếu có internal session token |

### AI providers

| Variable | Secret | Purpose |
|---|---:|---|
| OPENAI_API_KEY | Yes | Server-side OpenAI credential |
| OPENAI_PROJECT_ID | Yes/No | Project routing nếu áp dụng |
| OPENAI_CV_MODEL | No | Structured CV extraction model alias |
| OPENAI_EVALUATION_MODEL | No | Interview/CV evaluation model alias |
| OPENAI_EMBEDDING_MODEL | No | Embedding model alias |
| OPENAI_SEARCH_MODEL | No | Web search-capable model alias |
| OPENAI_TIMEOUT_SECONDS | No | Provider timeout |
| OPENAI_DAILY_BUDGET_MINOR | No | Cost guardrail |
| GEMINI_API_KEY | Yes | Gemini Live credential |
| GEMINI_LIVE_MODEL | No | Realtime model alias |
| GEMINI_LIVE_SESSION_LIMIT | No | Application concurrency cap |

Model name không hard-code trong domain. Thay model/config đi qua versioned model configuration và evaluation.

### Billing

| Variable | Secret | Purpose |
|---|---:|---|
| PAYMENT_PROVIDER | No | Adapter selection |
| PAYMENT_API_KEY | Yes | Provider credential |
| PAYMENT_WEBHOOK_SECRET | Yes | Raw-body signature verification |
| PAYMENT_SUCCESS_URL_ALLOWLIST | No | Redirect policy |

### Observability

| Variable | Secret | Purpose |
|---|---:|---|
| OTEL_SERVICE_NAME | No | Service/process identity |
| OTEL_EXPORTER_OTLP_ENDPOINT | No/Yes | Collector endpoint |
| OTEL_EXPORTER_OTLP_HEADERS | Yes | Collector credential nếu cần |
| TRACE_SAMPLE_RATIO | No | Baseline trace sampling |
| ERROR_REPORTING_DSN | Yes | Optional error platform |

Không đưa user email, CV text, transcript hoặc source URL đầy đủ vào metric labels.

## 6. Database migration

Release order:

1. Deployment team chụp/kiểm tra backup theo change risk.
2. Chạy migration job một lần bằng image release mới.
3. Migration kiểm tra advisory lock để không chạy song song.
4. Migration hoàn tất trước khi tăng traffic cho code cần schema mới.
5. Deploy theo expand/compatible phase.
6. Backfill chạy bằng job riêng có checkpoint, rate limit và metrics.
7. Contract migration chỉ ở release sau rollback window.

Migration job phải trả exit code khác 0 khi fail và không đánh dấu thành công một phần. Backend release note phải nêu estimated duration, lock risk, disk/index growth, backfill và rollback/roll-forward.

API readiness phải fail nếu schema quá cũ hoặc quá mới so với compatibility range của binary.

## 7. Network và edge requirements

Deployment team cấu hình:

- TLS end-to-end tới origin.
- Chỉ Cloudflare/load balancer được truy cập public origin nếu topology cho phép.
- WebSocket và SSE không bị buffering/timeout sai.
- Request ID được forward hoặc tạo mới đúng chuẩn.
- Upload body lớn đi trực tiếp R2; API JSON body có giới hạn nhỏ.
- WAF/rate policy coarse ở edge; application vẫn dùng distributed user/action rate limit.
- CORS allowlist cụ thể, không wildcard với credential.
- Payment webhook route giữ raw body và không bị cache.
- Admin/ops route có policy truy cập bổ sung nếu phù hợp.

Egress phải cho OpenAI, Gemini Live, OIDC, payment, R2 và nguồn job được phép; không mở tùy tiện nếu nền tảng hỗ trợ policy.

## 8. Health và startup

| Endpoint | Public | Semantics |
|---|---:|---|
| <code>/health/live</code> | Yes | Process/event loop còn hoạt động; không gọi provider ngoài |
| <code>/health/ready</code> | Yes, detail tối thiểu | Instance nhận traffic được; DB/schema bắt buộc tương thích |
| Dependency diagnostics chi tiết | No | Ops scope/private network; provider/queue/DB status đã redact |

Startup:

1. Validate config và secret presence.
2. Initialize telemetry.
3. Kiểm tra schema compatibility.
4. Initialize pool/client.
5. Chỉ sau đó readiness thành công.

Provider AI không nên làm liveness fail. Provider outage tạo degraded metric/circuit state và error có thể retry.

## 9. Observability và SLO

Dashboard tối thiểu:

- REST rate, error, p50/p95/p99 duration theo route template.
- Active WebSocket, reconnect, voice RTT, provider disconnect.
- Queue depth, oldest age, attempt/failure/dead-letter theo queue.
- PostgreSQL pool, transaction/error, slow query, storage/index growth.
- Redis latency/error/memory/eviction.
- R2 upload/download/error/checksum.
- OpenAI/Gemini request, latency, error, token/audio/search usage và estimated cost.
- Job discovered/verified/stale rate và source health.
- Credit reservation age, settlement/release và reconciliation mismatch.
- Webhook backlog/duplicate/signature failure.
- Privacy request age/failure.
- Product funnel ở dạng aggregate không lộ PII.

Alert phải có owner, severity, runbook và chống flapping. SLO target nằm trong [Non-functional Requirements](../requirements/non-functional-requirements.md).

## 10. Backup, restore và retention

Deployment team:

- Cấu hình managed PostgreSQL backup/PITR phù hợp RPO 24 giờ và RTO 4 giờ pilot.
- Cấu hình R2 lifecycle/versioning theo retention.
- Bảo vệ backup bằng encryption và quyền riêng.
- Thực hiện restore rehearsal ít nhất hàng quý.

Backend team:

- Cung cấp consistency check sau restore.
- Ghi rõ dữ liệu derived có thể rebuild: embeddings, search document, cache.
- Cung cấp reconciliation cho outbox/webhook/credit.
- Bảo đảm retention/deletion job hoạt động trên DB và R2.
- Version schema để binary phục hồi tương thích.

Restore runbook phải xử lý provider webhook/event có thể đến trong thời gian recovery và tránh double settlement.

## 11. Rollout và rollback

Khuyến nghị deployment team dùng canary hoặc rolling rollout:

1. Migration tương thích.
2. Deploy tỷ lệ nhỏ.
3. Kiểm tra health, error, latency, queue, provider cost và business invariant.
4. Tăng traffic theo gate.
5. Giữ image trước để rollback.

Rollback application không được rollback database destructively. Nếu schema đã expand, binary cũ phải tương thích; nếu không, dùng roll-forward fix. Model/prompt config rollback độc lập bằng activate version cũ.

Feature flag phù hợp cho live web search, model version, reranker và billing enforcement; flag không được bỏ qua authorization hoặc migration invariant.

## 12. Incident degradation

| Failure | Expected behavior |
|---|---|
| OpenAI unavailable | CV/evaluation/search explanation chuyển retry/degraded; indexed job read vẫn hoạt động |
| Gemini Live unavailable | Chặn session mới hoặc trả retryable; không mất transcript đã persist; release credit đúng |
| Job source unavailable | Hoàn tất partial với provenance/degraded reason; không gắn verified mới |
| Redis unavailable | Readiness/degradation theo dependency; không fallback rate limit bằng process memory trong production |
| R2 unavailable | Chặn upload/download; metadata transaction không giả complete |
| Worker backlog | API vẫn nhanh, trả status; alert queue age và áp dụng admission/quota |
| Payment provider unavailable | Không giả subscription/credit thành công; webhook retry/inbox/reconciliation |
| PostgreSQL unavailable | Readiness fail, không nhận business write; không dùng Redis làm source of truth |

## 13. Security handoff checklist

- OIDC issuer/audience/JWKS đúng environment.
- Admin/ops scope và access policy được test.
- Secret rotation procedure cho AI, R2, payment, OTel.
- R2 bucket private, CORS/signed URL TTL tối thiểu.
- Database/Redis TLS và network restriction.
- Container non-root, dependency/image scan.
- WAF/rate limit và application distributed quota.
- Raw webhook signature test/replay protection.
- Log/trace redaction test.
- File upload quarantine/malware policy.
- Data export/deletion và backup retention.
- Break-glass access có audit.

## 14. Backend production readiness gates

| Gate | Trạng thái | Owner / bằng chứng cần có |
|---|---|---|
| Migration chain, Product v1 domain schema | Implemented | Backend; Alembic revisions và migration test |
| OIDC/session, ownership/scope, account control | Implemented | Backend contract/security tests; deployment inject issuer/audience |
| CV draft-confirm, immutable version và lineage | Implemented | Backend contract tests và provider evaluation dataset |
| Hybrid job search, verification, rerank và provenance | Implemented, provider evidence pending | Backend; staging source/search quality report |
| Credit ledger, reservation/reconciliation và dual control | Implemented | Backend contract/concurrency tests |
| Gemini Live realtime/reconnect/backpressure | Partial | Backend + deployment; staging voice and WebSocket load evidence |
| Payment checkout và signed webhook | Partial | Backend + payment owner; provider certification/replay evidence |
| R2, managed Redis/PostgreSQL integration | Environment pending | Deployment provisions; backend runs integration suite/config validation |
| Logs/metrics/traces, dashboards và alerts | Instrumented, platform pending | Backend emits telemetry; deployment owns collector/dashboard/alerts |
| Load, security, migration và restore acceptance | Evidence pending | Joint release gate; results linked from release record |

`Implemented` ở bảng này chỉ xác nhận artifact backend; không thay thế hạ tầng, SLO hoặc provider acceptance do deployment team chịu trách nhiệm.

## 15. Handoff artifacts

Mỗi lần bàn giao deployment cần:

- Image digest và process matrix.
- Config/secret diff.
- Migration plan và command.
- OpenAPI/version.
- Required ports/protocols, WebSocket/SSE timeout.
- Resource baseline và autoscaling signals.
- Health checks.
- Dashboard/alerts/runbooks.
- Backup/restore requirement.
- Rollback/degradation plan.
- Known risk và feature flag state.

Logical schema: [Database Schema](../database/schema.md). API contract: [OpenAPI](../api/openapi.yaml). Kiến trúc: [Overview](../architecture/overview.md).
