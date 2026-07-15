# Non-functional Requirements

## 1. Phạm vi và giả định tải

Product v1 được thiết kế cho pilot production:

- 1.000 monthly active users.
- 50 REST requests đồng thời ở steady state.
- 20 interview voice sessions đồng thời.
- Background workload gồm CV extraction, evaluation, job verification, embeddings và privacy export.
- Mục tiêu dưới đây đo tại service boundary, không bao gồm latency mạng từ thiết bị người dùng đến Cloudflare nếu có ghi chú loại trừ.

SLO là mục tiêu vận hành, không phải tuyên bố rằng demo hiện tại đã đạt.

## 2. Availability và resilience

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-AVL-001 | API production phải đạt availability hàng tháng. | Tối thiểu 99,5% cho authenticated REST API, loại trừ maintenance đã thông báo và outage provider nằm ngoài control nhưng phải có degradation rõ. |
| NFR-AVL-002 | Health model phải tách liveness và readiness. | Liveness không phụ thuộc provider ngoài; readiness phản ánh DB và dependency bắt buộc để nhận traffic. |
| NFR-AVL-003 | Tác vụ async phải chịu được retry và worker restart. | At-least-once delivery không tạo duplicate business effect; job có attempt, timeout, backoff và dead-letter/review state. |
| NFR-AVL-004 | External provider failure phải được cô lập. | Timeout hữu hạn, retry có jitter, circuit breaker/bulkhead; chức năng không liên quan vẫn hoạt động. |
| NFR-AVL-005 | Realtime interview phải có cơ chế reconnect. | Cho phép reconnect trong cửa sổ cấu hình; transcript sequence không mất hoặc trùng không kiểm soát; ngoài cửa sổ chuyển session sang interrupted. |

## 3. Performance và capacity

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-PERF-001 | REST read latency | p95 dưới 500 ms và p99 dưới 1.500 ms ở tải pilot, loại trừ operation gọi provider đồng bộ được công bố. |
| NFR-PERF-002 | REST write latency | p95 dưới 1.000 ms cho write đã persist/enqueue, không chờ CV scan/evaluation/search hoàn tất. |
| NFR-PERF-003 | CV extraction | 95% scan PDF hợp lệ hoàn thành draft trong 60 giây; timeout/failure có status truy vấn được. |
| NFR-PERF-004 | Indexed job search | p95 dưới 1 giây cho FTS/vector/filter và trả page đầu ở dataset pilot. |
| NFR-PERF-005 | Live web job search | p95 dưới 15 giây để có batch verified đầu tiên; phần còn lại stream bằng SSE. |
| NFR-PERF-006 | Voice interaction | p95 round-trip từ speech event nhận tại edge API đến audio response bắt đầu dưới 1,5 giây khi Gemini Live khỏe. |
| NFR-PERF-007 | Pilot concurrency | Không vượt error budget ở 50 REST concurrent và 20 voice sessions concurrent; background queue không làm đói realtime traffic. |
| NFR-PERF-008 | Database query discipline | Endpoint collection không có N+1; query p95 và slow-query threshold được đo; index usage được review trước release. |

## 4. Data durability và recovery

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-DATA-001 | PostgreSQL recovery point objective | RPO tối đa 24 giờ cho pilot; transaction log/PITR được ưu tiên khi managed service hỗ trợ. |
| NFR-DATA-002 | Recovery time objective | RTO tối đa 4 giờ cho database/service trong pilot. |
| NFR-DATA-003 | Object durability | PDF/artifact dùng object storage production có versioning hoặc lifecycle phù hợp; checksum được kiểm tra khi upload/restore. |
| NFR-DATA-004 | Restore test | Thực hiện restore rehearsal ít nhất mỗi quý và ghi thời gian, dữ liệu thiếu, action item. |
| NFR-DATA-005 | Consistency | Business invariant quan trọng dùng transaction/constraint; outbox/reconciliation cho side effect qua provider. |
| NFR-DATA-006 | Migration safety | Migration production theo expand/backfill/contract, không yêu cầu downtime ngoài maintenance window đã công bố. |

## 5. Security

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-SEC-001 | Transport và storage encryption | TLS 1.2+ bên ngoài; managed encryption at rest cho DB/object/backup; secret không nằm trong image/repository. |
| NFR-SEC-002 | Authentication | Xác minh JWT signature, issuer, audience, expiry; key rotation không cần redeploy toàn hệ thống. |
| NFR-SEC-003 | Authorization | Deny by default; ownership và role/scope test cho mọi endpoint protected; admin action audit. |
| NFR-SEC-004 | Abuse protection | Distributed rate limit/quota theo user, IP và action; WAF cho pattern phổ biến; limit riêng cho AI-cost endpoints. |
| NFR-SEC-005 | File security | Allowlist PDF, giới hạn size, checksum, malware/quarantine state, object key do server cấp. |
| NFR-SEC-006 | Application security | Threat model cho release lớn; dependency/container scan; vá critical vulnerability theo SLA nội bộ tối đa 7 ngày. |
| NFR-SEC-007 | Webhook security | Signature, timestamp/replay window và idempotent inbox bắt buộc. |
| NFR-SEC-008 | Logging safety | Không log token, API key, signed URL đầy đủ, CV/transcript đầy đủ hoặc payment payload chưa redact. |

## 6. Privacy và compliance readiness

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-PRIV-001 | Data minimization | Chỉ thu thập field phục vụ product purpose; mỗi nhóm dữ liệu có owner, purpose và retention. |
| NFR-PRIV-002 | User control | Export và deletion có SLA được công bố; trạng thái xử lý và ngoại lệ retention có thể giải thích. |
| NFR-PRIV-003 | Consent separation | Product processing, marketing và model-training consent là các record độc lập, versioned và có thể rút khi áp dụng. |
| NFR-PRIV-004 | Provider transfer | Chỉ gửi subset dữ liệu cần thiết; provider/config region và retention được review; không bật training mặc định. |
| NFR-PRIV-005 | Retention enforcement | Scheduler xóa/anonymize dữ liệu quá hạn; có metric, audit và retry; backup expiration được tính trong policy. |
| NFR-PRIV-006 | Least privilege support | Support/admin chỉ thấy dữ liệu tối thiểu, có masking và access audit. |

## 7. Observability và operations

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-OBS-001 | Correlation | 100% request có request ID; async run/job/model call giữ trace/correlation qua boundary. |
| NFR-OBS-002 | Metrics | Có RED metrics cho API, queue depth/age, DB pool, provider latency/error/cost, interview concurrency và job freshness. |
| NFR-OBS-003 | Structured logs | JSON log có service, environment, request/run ID, event, severity và safe error code; không phụ thuộc message parsing. |
| NFR-OBS-004 | Tracing | Trace bao phủ API, DB, queue và provider call quan trọng; sampling có thể cấu hình và tăng khi incident. |
| NFR-OBS-005 | Alerting | Alert dựa trên SLO/error budget, queue age, credit reconciliation, webhook backlog và provider degradation; có runbook owner. |
| NFR-OBS-006 | Audit | Security/admin/billing/privacy event là append-only logic, truy vấn được và retention dài hơn application logs. |

## 8. AI quality, safety và cost

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-AI-001 | Structured output reliability | 100% output đi qua schema validation; invalid output retry/repair hữu hạn rồi chuyển failure state, không lưu canonical data. |
| NFR-AI-002 | CV extraction quality | Evaluation set đại diện tiếng Việt/Anh; field-level precision/recall threshold được định nghĩa trước release và theo dõi theo model version. |
| NFR-AI-003 | Interview evaluation consistency | Rubric versioned; regression evaluation đo agreement/variance; report phải trích evidence từ transcript. |
| NFR-AI-004 | Job citation validity | Kết quả live có source URL và checked_at; explanation không đưa claim quan trọng ngoài candidate/job evidence. |
| NFR-AI-005 | Cost control | Token/search/audio usage ghi theo user/action/model; budget, quota và alert theo ngày/tháng; chỉ top results dùng LLM explanation. |
| NFR-AI-006 | Model change safety | Model/prompt update qua staged rollout, offline eval và rollback; run cũ vẫn truy được version đã dùng. |
| NFR-AI-007 | Human control | User chỉnh CV draft và báo lỗi output; AI không tự quyết định eligibility hoặc tuyển dụng. |

## 9. Maintainability và compatibility

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-MNT-001 | Modular boundary | Domain logic không import trực tiếp provider SDK; adapter có interface và contract test. |
| NFR-MNT-002 | API compatibility | Breaking change cần version mới/deprecation window; OpenAPI operation ID và error code ổn định. |
| NFR-MNT-003 | Testability | Test mặc định không phụ thuộc Internet/API trả phí; provider dùng mock/fixture; integration dependency chạy qua container. |
| NFR-MNT-004 | Configuration | Config validate khi startup; production thiếu secret/config bắt buộc phải fail fast; không có secret default. |
| NFR-MNT-005 | Documentation traceability | Requirement, API operation, logical entity và test có thể truy vết; status demo/target không nhập nhằng. |
| NFR-MNT-006 | Runtime portability | Backend cung cấp OCI-compatible image, chạy stateless ngoài DB/cache/object store và graceful shutdown. |

## 10. Accessibility và localization

| ID | Requirement | Target / acceptance |
|---|---|---|
| NFR-UX-001 | Language | Product v1 hỗ trợ nội dung CV/job tiếng Việt và tiếng Anh; dữ liệu gốc không bị dịch âm thầm. |
| NFR-UX-002 | Time/currency | API dùng UTC/ISO 8601 và ISO 4217; client chịu trách nhiệm format theo locale. |
| NFR-UX-003 | Realtime fallback | Khi voice không khả dụng, trạng thái và lỗi phải cho phép user retry hoặc tiếp tục bằng flow được hỗ trợ, không mất transcript đã persist. |

## 11. Phương pháp đo

- SLO lấy từ metrics production và synthetic probes, tính theo cửa sổ rolling 30 ngày.
- Load test dùng workload tách REST, CV jobs, SSE và WebSocket; không suy ra voice capacity từ REST test.
- AI quality dùng evaluation dataset versioned, không dùng production PII thô trong CI.
- RPO/RTO chỉ được coi là đạt sau restore rehearsal.
- Mỗi exception phải có owner, expiry date và risk acceptance.
