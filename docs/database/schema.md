# Database Schema

## 1. Phạm vi

Đây là logical schema chuẩn cho QATTH Product v1. Backend đã quản lý physical schema bằng Alembic; tài liệu vẫn mô tả thêm invariant/index cần được kiểm tra trên PostgreSQL production thay vì thay thế migration source code.

## 2. Quyết định lưu trữ

| Dữ liệu | Nơi lưu | Lý do |
|---|---|---|
| User, state machine, version, billing, audit | PostgreSQL | Transaction, constraint, query và lịch sử |
| Field linh hoạt/versioned | PostgreSQL JSONB | Giữ schema version và payload có cấu trúc, vẫn nằm trong transaction |
| Job lexical document | PostgreSQL <code>tsvector</code> | Full-text search và filter cùng database |
| Embedding | pgvector <code>vector(n)</code> | Semantic retrieval kết hợp dữ liệu quan hệ/FTS |
| PDF, raw JD, audio/export artifact | Cloudflare R2 | Blob lớn, lifecycle và signed URL |
| Cache, rate limit, ephemeral coordination | Redis | TTL và distributed atomic operation |
| Secret/API key | Secret manager do deployment team cung cấp | Không thuộc database/application image |

Không lưu PDF trong PostgreSQL trừ artifact rất nhỏ có lý do được ADR chấp thuận. Database lưu object key, checksum, metadata và ownership.

### Migration coverage hiện tại

| Revisions | Phạm vi |
|---|---|
| Foundation đến <code>0006</code> | Core schema, background tasks, file assets, model runs, security/privacy và candidate discovery |
| <code>0007</code>-<code>0014</code> | Identity/profile/consent, Product CV, interview, job search, recommendation, billing, privacy và admin/ops |
| <code>0015</code>-<code>0019</code> | Identity/file/CV hardening, interview hardening, job search hardening, billing dual-control và provider usage observability |
| <code>0020</code>-<code>0023</code> | Payment inbox/reconciliation, billable interview boundary, recommendation feedback và auditable ranking v2 |
| <code>0024</code>-<code>0028</code> | OIDC provider-session identity, catalog schedule invariants, cumulative payment reversal/account review, durable AI dispatch và worker processing leases |
| <code>0029</code>-<code>0030</code> | Persisted async-run correlation và transactional outbox cho admin background-job retry |
| <code>0031</code> | DB-enforced immutability cho privacy audit events |

Migration trong <code>migrations/versions/</code> là lịch sử physical schema bất biến. Bảng/constraint trong tài liệu chưa có revision tương ứng phải được coi là gap và cần migration riêng; không dùng <code>create_all</code> để thay thế migration ở production.

## 3. Quy ước chung

- Primary key: UUID/UUIDv7 hoặc sortable opaque ID do server tạo.
- Timestamp: <code>timestamptz</code> UTC; bảng mutable có <code>created_at</code>, <code>updated_at</code>.
- Soft delete chỉ dùng khi business/audit cần; không thay thế privacy deletion.
- State dùng enum/check constraint và transition trong domain service.
- JSONB phải có <code>schema_version</code> khi payload cần tiến hóa.
- Tiền lưu integer minor unit + ISO 4217 currency; credit lưu integer.
- URL/object key không chứa email/tên người dùng.
- Mọi unique key nhận từ provider phải scope theo provider/source.
- Bảng event/ledger/outbox là append-only ở application permission.
- Table name dùng snake_case plural.

## 4. Extensions

~~~sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
~~~

UUID generation có thể ở application hoặc database nhưng phải thống nhất. <code>pg_trgm</code> chỉ dùng cho fuzzy lookup đã benchmark, không thay FTS.

## 5. Identity, privacy và audit

### users

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| status | text | active, locked, pending_deletion, deleted |
| primary_email_normalized | citext/text | nullable, unique partial khi có |
| display_name | text | nullable |
| locale | text | mặc định vi-VN |
| timezone | text | IANA name |
| profile | jsonb | public/career profile linh hoạt, schema-versioned |
| deleted_at | timestamptz | nullable |
| created_at, updated_at | timestamptz | required |

Không dùng email làm foreign key hoặc object key.

### auth_identities

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| user_id | uuid | FK users |
| issuer | text | OIDC issuer |
| subject | text | OIDC subject |
| claims_snapshot | jsonb | allowlisted claims, không lưu token |
| last_login_at | timestamptz | nullable |
| created_at | timestamptz | required |

Unique <code>(issuer, subject)</code>; index <code>(user_id)</code>.

### user_sessions

Lưu session/revocation: <code>id</code>, <code>user_id</code>, identity ID, hashed token fingerprint, provider session ID nullable, <code>expires_at</code>, <code>revoked_at</code>, device metadata tối thiểu, timestamps. Unique partial <code>(identity_id, provider_session_id)</code> khi provider có <code>sid</code> để token refresh không vượt qua revocation; nếu không có <code>sid</code>, fingerprint là identity của session. Không lưu bearer token plaintext. Account chỉ được auto-link bằng email khi OIDC xác nhận <code>email_verified=true</code>.

### user_job_preferences

Một record active theo user hoặc versioned rows gồm role keywords, locations, remote modes, employment types, salary range/currency, target seniority, skills, exclusions và <code>version</code>. Matching run lưu preference version/snapshot đã dùng.

### consent_records

<code>id</code>, <code>user_id</code>, <code>purpose</code>, <code>policy_version</code>, <code>status</code>, <code>granted_at</code>, <code>withdrawn_at</code>, <code>evidence</code> JSONB, timestamps.

Unique logic không cho hai trạng thái active cho cùng <code>(user_id, purpose, policy_version)</code> nếu policy yêu cầu.

### audit_events

Append-only: <code>id</code>, <code>occurred_at</code>, actor user/service, action, resource type/ID, request ID, IP hash/metadata tối thiểu, outcome, reason, safe details JSONB.

Index theo <code>(resource_type, resource_id, occurred_at)</code>, <code>(actor_id, occurred_at)</code>, <code>(request_id)</code>. Audit không chứa CV/transcript đầy đủ.

### privacy_requests

<code>id</code>, <code>user_id</code>, type export/deletion, status, requested/completed timestamps, checkpoint JSONB, retention exceptions, artifact file ID, failure code và idempotency key. Unique idempotency key theo user/action.

## 6. File và CV domain

### file_assets

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| owner_user_id | uuid | FK users |
| purpose | text | cv_source, raw_job, transcript, export... |
| provider | text | r2 |
| bucket | text | logical bucket |
| object_key | text | unique, server-generated |
| content_type | text | allowlisted |
| size_bytes | bigint | positive, bounded |
| sha256 | text | 64 hex chars |
| upload_status | text | pending, uploaded, rejected, deleted |
| security_status | text | pending, clean, quarantined, failed |
| retention_until | timestamptz | nullable |
| deleted_at | timestamptz | nullable |
| metadata | jsonb | provider/version metadata |
| created_at, updated_at | timestamptz | required |

Unique <code>(provider, bucket, object_key)</code>. Index owner/time và retention cleanup.

### cvs

<code>id</code>, <code>user_id</code>, title, status active/archived/deleting, <code>active_version_id</code> nullable, timestamps. Active version FK được thêm deferrable hoặc validate trong transaction để tránh vòng phụ thuộc migration.

### cv_scan_runs

<code>id</code>, <code>user_id</code>, <code>cv_id</code> nullable, <code>source_file_id</code>, status, schema version, current attempt, idempotency key, error code, processing lease ID/expiry, queued/started/completed timestamps, created_at.

Unique <code>(user_id, idempotency_key)</code> khi key có. Index status/queued_at cho worker và user/created_at cho history.

### cv_scan_attempts

Append-only attempt: <code>id</code>, <code>scan_run_id</code>, attempt number, <code>model_run_id</code>, status, extraction artifact JSONB, warnings JSONB, error code, started/completed timestamps. Unique <code>(scan_run_id, attempt_no)</code>.

### cv_drafts

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| scan_run_id | uuid | FK, unique active draft per scan |
| user_id | uuid | ownership query |
| revision | integer | optimistic concurrency, positive |
| schema_version | text | extraction schema |
| content | jsonb | editable structured CV |
| warnings | jsonb | confidence/validation warnings |
| status | text | editable, confirmed, discarded |
| confirmed_version_id | uuid | nullable FK cv_versions |
| created_at, updated_at | timestamptz | required |

PATCH dùng <code>revision</code> hoặc ETag; confirm transaction kiểm tra status/revision.

### cv_versions

Immutable after insert: <code>id</code>, <code>cv_id</code>, <code>version_no</code>, <code>schema_version</code>, <code>content</code> JSONB, content checksum, source draft/scan ID, created_by user/service, <code>created_at</code>.

Unique <code>(cv_id, version_no)</code> và <code>(cv_id, checksum)</code> theo policy. Index GIN chỉ cho path truy vấn thực; không index toàn payload mặc định.

### cv_analyses

<code>id</code>, <code>cv_version_id</code>, status, rubric version, findings JSONB, score summary JSONB, <code>model_run_id</code>, error code, timestamps. Có thể nhiều analysis version; chỉ active/latest do query chọn, không overwrite.

## 7. Interview domain

### interview_sessions

<code>id</code>, <code>user_id</code>, status, interview type, target role, CV version ID, optional job snapshot ID, plan/rubric versions, input snapshot JSONB, Gemini session metadata an toàn, reconnect deadline, started/ended timestamps, idempotency key, timestamps.

Index user/created_at, status/reconnect_deadline. Unique user/idempotency key.

### interview_events

Append-only ordered log: <code>id</code>, <code>session_id</code>, <code>sequence_no</code>, event type, speaker, occurred_at, text content nullable, artifact file ID nullable, provider event ID nullable, safe metadata JSONB.

Unique <code>(session_id, sequence_no)</code>; unique partial <code>(session_id, provider_event_id)</code>. Partitioning theo time chỉ đánh giá khi volume thực yêu cầu.

### interview_evaluations

<code>id</code>, <code>session_id</code>, version, status, rubric version, scores/findings/evidence JSONB, report artifact ID nullable, model run ID, processing lease ID/expiry, error code, timestamps. Unique <code>(session_id, version)</code>; evidence tham chiếu sequence/event tồn tại ở application validation.

## 8. Job discovery và search

### job_sources

<code>id</code>, key, display name, source type, base domain, status, access policy JSONB, verification TTL, quality score, last healthy timestamp, timestamps. Unique key/domain theo policy.

### job_postings

Canonical normalized job:

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| canonical_fingerprint | text | dedup key/versioned algorithm |
| title | text | required |
| company_name | text | required khi biết |
| location_text | text | nullable |
| remote_mode | text | onsite, hybrid, remote, unknown |
| employment_type | text | nullable |
| seniority | text | nullable |
| salary_min_minor, salary_max_minor | bigint | nullable, non-negative |
| salary_currency | char(3) | nullable |
| description_text | text | sanitized normalized JD |
| requirements | jsonb | structured skills/experience/education |
| skills | text[]/jsonb | normalized IDs/names |
| language | text | detected/source language |
| status | text | active, stale, expired, invalid |
| first_seen_at, last_seen_at | timestamptz | required |
| verified_at, expires_at | timestamptz | nullable |
| search_document | tsvector | generated/materialized |
| normalization_version | text | required |
| created_at, updated_at | timestamptz | required |

Index:

- GIN <code>(search_document)</code>.
- B-tree status/expires_at, verified_at, company/title filters.
- GIN skills nếu access pattern chứng minh.
- Trigram index có chọn lọc cho company/title dedup.

### job_source_records

Ánh xạ canonical job với nguồn: <code>id</code>, <code>job_posting_id</code>, <code>source_id</code>, source job ID, source URL, status, first/last seen, last checked, HTTP/fetch outcome, raw snapshot file ID, metadata JSONB.

Unique <code>(source_id, source_job_id)</code> khi có và normalized URL fingerprint khi không có.

### job_snapshots

Immutable normalized/source snapshot: <code>id</code>, job ID, source record ID, content hash, normalized payload JSONB, raw file ID, parser version, captured_at. Unique source record/content hash để tránh duplicate.

### job_embeddings

<code>id</code>, <code>job_posting_id</code>, <code>job_snapshot_id</code>, embedding model/version, dimension, <code>embedding vector(n)</code>, content hash, created_at.

Unique job snapshot/model version. Chọn HNSW hoặc IVFFlat sau benchmark; filter status/freshness trước hoặc dùng query plan phù hợp.

### job_search_runs

<code>id</code>, user ID, status, mode indexed/live/hybrid, query text, filters JSONB, candidate profile version, provider/query version, progress JSONB, idempotency key, started/completed timestamps, error/degradation codes, timestamps.

### job_search_results

<code>id</code>, run ID, job ID, rank, lexical/vector/freshness/source/rerank scores, score breakdown JSONB, final score, explanation model run ID nullable, explanation JSONB nullable, result snapshot JSONB, created_at. Breakdown ranking v2 lưu retrieval fusion, CV skill, role/location/work-mode preference, interview-supported fit, freshness, source quality và final score để replay/debug offline.

Unique <code>(run_id, job_id)</code> và <code>(run_id, rank)</code>. Score breakdown nội bộ có access policy.

### job_interactions

<code>id</code>, user ID, job ID, type viewed/saved/dismissed/reported, metadata, occurred_at. Unique hoặc upsert policy theo user/job/type; event analytics có thể tách nếu cần mọi lần view.

### job_applications và application_events

Application: user/job, current status, source URL, note, applied_at, timestamps. Event append-only: application ID, from/to status, actor, note, occurred_at. Unique active application theo user/job tùy product rule.

## 9. Recommendation domain

### candidate_profiles

Versioned derived profile: <code>id</code>, user ID, version, CV version ID, preference version/snapshot, interview evaluation IDs, structured profile JSONB, embedding vector(n) nullable, model/version, status fresh/stale, created_at.

### recommendation_runs

<code>id</code>, user ID, candidate profile ID, source search run ID nullable, ranking version, config snapshot, status, idempotency key, timestamps.

### recommendation_matches

<code>id</code>, match run ID, job ID/snapshot ID, rank, score components JSONB, final score, explanation JSONB, model run ID nullable. Unique run/job và run/rank.

### recommendation_feedback

Append-only evaluation event: <code>id</code>, user ID, recommendation run/match/job IDs, event taxonomy, reason/note, ranking version, server-side experiment assignment, rank/score context snapshot, training eligibility và consent snapshot, idempotency key, created_at. Unique <code>(user_id, idempotency_key)</code>. Client không được gửi authoritative experiment, rank, score hoặc training eligibility.

## 10. Billing domain

Normative business rules và catalog baseline nằm trong [Pricing and Credits Specification](../billing/pricing-and-credits.md). Database không hard-code giá vào domain logic; seed catalog chỉ là data migration.

### pricing_catalog_versions

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| version_key | text | Human-readable immutable version |
| market | text | Ví dụ VN |
| currency | char(3) | VND cho baseline |
| status | text | draft, active, retired |
| effective_from, effective_to | timestamptz | Non-overlapping active range |
| created_by_user_id | uuid | Nullable FK users |
| published_by_user_id | uuid | Nullable FK users |
| created_at, published_at | timestamptz | Audit timestamps |
| metadata | jsonb | Tax/legal/catalog notes |

Unique version key. Transactional predecessor/successor scheduling giữ effective ranges không chồng nhau; unique partial <code>(market, currency)</code> cho published row có <code>effective_to IS NULL</code> bảo đảm chỉ một open-ended tail kể cả khi activate đồng thời. Published version không update pricing; thay đổi tạo version mới.

### billing_offers và billing_offer_prices

Offer:

- <code>id</code>, catalog version ID, internal code, display name.
- <code>offer_type</code>: subscription hoặc topup.
- <code>billing_interval</code>: month cho subscription, null cho top-up.
- <code>credit_grant</code> positive integer.
- status active/inactive, sort order và safe metadata.
- Unique <code>(catalog_version_id, code)</code>.

Price:

- <code>id</code>, offer ID, currency, <code>amount_minor</code>, tax behavior và effective range.
- VND dùng integer amount theo ISO 4217, không float.
- Unique active price theo offer/currency/effective range.

Baseline seed version <code>2026-07-14-product-v1-draft</code>:

| Offer | Type | Amount minor | Credit grant |
|---|---|---:|---:|
| STARTER_MONTHLY | subscription | 49000 | 60 |
| PRO_MONTHLY | subscription | 99000 | 150 |
| PREMIUM_MONTHLY | subscription | 199000 | 350 |
| TOPUP_STARTER | topup | 70000 | 70 |
| TOPUP_PRO | topup | 100000 | 105 |
| TOPUP_PREMIUM | topup | 200000 | 220 |
| TOPUP_MAX | topup | 300000 | 335 |

### feature_credit_prices

<code>id</code>, catalog version ID, feature key, non-negative credit cost, optional duration/quota policy JSONB, created/published audit fields. Unique <code>(catalog_version_id, feature_key)</code>.

Baseline:

- <code>cv_upload=0</code>.
- <code>cv_analysis=10</code>.
- <code>search_run=0</code>.
- <code>interview_session=25</code> với maximum duration 30 phút.

Zero cost là hợp lệ và vẫn yêu cầu usage telemetry/quota.

### signup_trial_policies

Versioned policy: <code>id</code>, policy key, status, enabled, trigger, credit amount, valid days, grants-per-user, effective range, actor/timestamps.

Baseline policy: trigger verified email, 50 credits, 7 days, một grant/user. Published policy không update tại chỗ.

### payment_provider_mappings

<code>id</code>, provider, offer/price ID, provider product/price identifier, status, effective range, metadata và timestamps. Unique provider/provider price ID. Mapping không làm provider ID trở thành canonical offer ID.

### checkout_sessions

<code>id</code>, user ID, offer/price/catalog IDs, provider, provider session/order ID, status, amount/currency/credit snapshot, idempotency key, redirect URL fingerprints, expires/completed timestamps.

Unique <code>(user_id, idempotency_key)</code> và provider session/order ID. Client không cung cấp authoritative amount/credit.

### subscriptions

<code>id</code>, user ID, internal offer/price/catalog IDs, provider/customer/subscription IDs, status, current period start/end, cancel flags, last provider event time, timestamps.

Unique provider subscription ID. Period credit grant tham chiếu subscription + period; cancel giữ period hiện tại, failed payment không tạo grant.

### payment_events và webhook_inbox

Webhook inbox:

- <code>id</code>, provider, provider event ID, event type, signature verified timestamp, received timestamp, status/attempts/error.
- Raw payload JSONB nếu an toàn hoặc encrypted object reference theo retention.
- Unique <code>(provider, provider_event_id)</code>.

Normalized payment event:

- <code>id</code>, inbox ID, event type, order/subscription references, amount/currency, occurred_at, normalized payload và processed timestamp.
- Unique inbox ID/event semantic key.
- Processing transaction cập nhật payment projection và credit grant idempotently.

### credit_accounts

Một account theo user:

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| user_id | uuid | FK users, unique |
| status | text | active, review, locked, closed |
| posted_balance | bigint | Optional transactionally maintained projection |
| reserved_balance | bigint | Optional projection, non-negative |
| version | bigint | Optimistic/accounting lock version |
| created_at, updated_at | timestamptz | Required |

Authoritative posted balance phải khớp ledger; available còn trừ active reservations và expired buckets. Projection được reconciliation kiểm tra.

### credit_grants và credit_buckets

Grant giữ nguồn business bất biến:

- <code>id</code>, account/user, source type trial/subscription/topup/adjustment.
- Source reference, offer/catalog/subscription/period/payment IDs.
- Granted amount, idempotency key, granted_at, metadata.
- Unique source business reference và account/idempotency key.

Bucket giữ allocation/expiry:

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| grant_id | uuid | FK credit_grants |
| account_id | uuid | FK credit_accounts |
| bucket_type | text | trial, subscription, topup, adjustment |
| granted_amount | bigint | Positive |
| consumed_amount | bigint | Non-negative |
| expired_amount | bigint | Non-negative |
| expires_at | timestamptz | Null cho non-expiring top-up |
| expiry_settled_at | timestamptz | Nullable |
| created_at | timestamptz | Required |

Constraint <code>granted_amount >= consumed_amount + expired_amount</code>. Available bucket còn trừ active reservation allocations. Index account/type/expires_at và pending expiry.

### credit_ledger_entries

Append-only:

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| account_id, bucket_id | uuid | Required account, nullable bucket khi adjustment đặc biệt |
| entry_type | text | GRANT, CHARGE, EXPIRE, REFUND, REVERSAL, ADJUSTMENT |
| amount | bigint | Signed, non-zero |
| balance_after | bigint | Posted account projection sau entry |
| reference_type, reference_id | text/uuid | Business provenance |
| idempotency_key | text | Unique scoped account |
| actor_type, actor_id | text/uuid | User/admin/service/provider |
| occurred_at | timestamptz | Required |
| metadata | jsonb | Safe reason/provider info |

Không update/delete posted row. <code>RELEASE</code> là reservation state/audit event và không cần ledger amount zero.

### usage_reservations

<code>id</code>, account/user, feature key, business resource, credit cost, pricing/catalog version, status reserved/settled/released/expired, idempotency key, request hash, billable started timestamp, expires_at, timestamps.

Unique account/operation/idempotency key và business resource/feature active reservation. Same key khác request hash trả conflict.

### reservation_allocations

<code>id</code>, reservation ID, bucket ID, allocated amount, status reserved/settled/released, settled ledger entry ID nullable, timestamps.

Unique reservation/bucket. Allocation theo trial earliest expiry, subscription earliest expiry, top-up oldest. Tổng allocations bằng reservation credit cost. Settle/release idempotent.

### account_reviews

<code>id</code>, account/user, provider/event unique reference, reason refund/chargeback/reconciliation, debt credit amount, status open/resolved/waived, details và timestamps. Payment reversal state riêng theo provider/period lưu original amount, cumulative reversed amount và reversed credits; cumulative rounding bảo đảm nhiều partial events không reverse vượt grant.

Refund reverse phần grant chưa dùng. Nếu grant đã dùng, account chuyển review/locked theo policy thay vì âm thầm tạo balance âm.

### Billing indexes and invariants

- Unique grant theo subscription + billing period.
- Unique trial grant theo user + policy purpose.
- Unique webhook theo provider/event ID.
- Unique ledger mutation theo account/idempotency key.
- Row lock/serializable strategy cho reserve/settle/release.
- Expiry settlement và reservation reconciliation có index theo status/time.
- Payment, ledger và audit retention độc lập application logs.
- Redis/cache không quyết định accounting correctness.
- Credit không transfer giữa users hoặc cash out.
## 11. AI, background work và integration

### prompt_versions

<code>id</code>, purpose, version, status draft/active/retired, template/config JSONB, output schema version, created/published actor/time. Unique purpose/version; active transition được audit.

### model_runs

<code>id</code>, user/resource, purpose, provider, model, prompt version ID, request/response schema versions, provider request ID, status, input/output artifact references hoặc redacted hashes, tokens/audio/search usage, estimated cost minor/currency, latency, error code, timestamps.

Không lưu prompt chứa PII đầy đủ trong log table nếu artifact policy không cho phép.

### background_jobs

<code>id</code>, type, queue, resource, status, priority, attempt/max attempts, idempotency key, scheduled/started/finished times, heartbeat, error code, safe payload/result JSONB. Unique type/idempotency key.

### outbox_events

Append-only: <code>id</code>, aggregate type/ID, event type, unique nullable deduplication key, payload JSONB, correlation ID, occurred/available/published timestamps, attempts và safe last error. Publisher định kỳ retry unpublished AI task dispatch với backoff; consumer kiểm tra resource state để chịu at-least-once delivery.

### idempotency_keys

<code>id</code>, scope user/system, key, operation, request hash, resource ID, response status/body reference, status, expires_at, timestamps. Unique scope/operation/key; cùng key khác request hash trả conflict.

## 12. Referential deletion policy

- User deletion không cascade mù qua billing/audit; dùng privacy workflow theo policy.
- CV version được report/match tham chiếu có thể giữ snapshot tối thiểu hoặc anonymize theo legal/product requirement.
- File asset xóa object trước/đồng bộ checkpoint rồi mark deleted; có retry/reconciliation.
- Job canonical có thể tồn tại độc lập user; interaction/application phải xóa/anonymize theo user.
- Model run xóa/anonymize PII artifact nhưng giữ aggregate cost/operational fields nếu policy cho phép.
- Ledger/audit giữ tối thiểu bắt buộc, pseudonymize user khi account bị xóa.

## 13. Migration strategy

1. Mỗi release tạo forward-only migration đã review.
2. Expand: thêm nullable column/table/index concurrently khi phù hợp.
3. Deploy code đọc/ghi tương thích cả schema cũ và mới.
4. Backfill bằng job có checkpoint, rate limit và metrics.
5. Chuyển read path, kiểm tra consistency.
6. Contract ở release sau khi rollback window kết thúc.
7. Không chạy migration tự động trong mọi API replica; dùng one-shot migration command trước rollout.
8. Backup/restore và migration từ database có dữ liệu phải được test trước production.

## 14. Kiểm tra bắt buộc

- Foreign key/unique/check constraint cho invariant.
- Query plan cho FTS/vector, user history và worker dequeue.
- Concurrent tests cho CV confirm, credit reserve và webhook duplicate.
- Migration test từ version production gần nhất.
- Deletion/export coverage map.
- Ledger/outbox reconciliation.
- Không có blob lớn hoặc secret trong row/log.
