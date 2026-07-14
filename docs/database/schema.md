# Database Schema

## 1. Phạm vi

Đây là logical schema mục tiêu cho QATTH Product v1, không phải bản sao schema demo hiện tại. Implementation phải chuyển thành migration PostgreSQL có review về constraint, index, lock, backfill và rollback.

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

Lưu session/revocation nếu kiến trúc dùng session token nội bộ: <code>id</code>, <code>user_id</code>, hashed token identifier, <code>expires_at</code>, <code>revoked_at</code>, device metadata tối thiểu, timestamps. Không lưu bearer token plaintext.

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

<code>id</code>, <code>user_id</code>, <code>cv_id</code> nullable, <code>source_file_id</code>, status, schema version, current attempt, idempotency key, error code, queued/started/completed timestamps, created_at.

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

<code>id</code>, <code>session_id</code>, version, status, rubric version, scores/findings/evidence JSONB, report artifact ID nullable, model run ID, error code, timestamps. Unique <code>(session_id, version)</code>; evidence tham chiếu sequence/event tồn tại ở application validation.

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

<code>id</code>, run ID, job ID, rank, lexical/vector/freshness/source/rerank scores, final score, explanation model run ID nullable, explanation JSONB nullable, result snapshot JSONB, created_at.

Unique <code>(run_id, job_id)</code> và <code>(run_id, rank)</code>. Score breakdown nội bộ có access policy.

### job_interactions

<code>id</code>, user ID, job ID, type viewed/saved/dismissed/reported, metadata, occurred_at. Unique hoặc upsert policy theo user/job/type; event analytics có thể tách nếu cần mọi lần view.

### job_applications và application_events

Application: user/job, current status, source URL, note, applied_at, timestamps. Event append-only: application ID, from/to status, actor, note, occurred_at. Unique active application theo user/job tùy product rule.

## 9. Recommendation domain

### candidate_profiles

Versioned derived profile: <code>id</code>, user ID, version, CV version ID, preference version/snapshot, interview evaluation IDs, structured profile JSONB, embedding vector(n) nullable, model/version, status fresh/stale, created_at.

### match_runs

<code>id</code>, user ID, candidate profile ID, source search run ID nullable, ranking version, config snapshot, status, idempotency key, timestamps.

### match_items

<code>id</code>, match run ID, job ID/snapshot ID, rank, score components JSONB, final score, explanation JSONB, model run ID nullable. Unique run/job và run/rank.

## 10. Billing domain

### plans và plan_prices

Plan giữ product entitlement/credit policy version. Price giữ provider price ID, currency, amount minor, interval, effective range. Không overwrite price lịch sử đã dùng.

### subscriptions

<code>id</code>, user ID, provider/customer/subscription IDs, plan/price IDs, status, current period, cancel flags, provider version/last event time, timestamps. Unique provider subscription ID.

### credit_accounts

Một account theo user/currency credit: <code>id</code>, user ID, status, optional cached balance với reconciliation, lock/version, timestamps. Unique user.

### credit_ledger_entries

Append-only:

| Column | Type | Constraint / meaning |
|---|---|---|
| id | uuid | PK |
| account_id | uuid | FK |
| amount | bigint | signed, non-zero |
| entry_type | text | grant, charge, refund, adjustment, expiry |
| reference_type, reference_id | text/uuid | business provenance |
| idempotency_key | text | unique scoped account |
| occurred_at | timestamptz | required |
| metadata | jsonb | safe reason/provider info |
| created_by | uuid/text | user/admin/service |

Balance authoritative bằng tổng posted entries; cached balance nếu có phải cập nhật cùng transaction và reconcile.

### usage_reservations

<code>id</code>, account ID, user/action/resource, amount, status reserved/settled/released/expired, idempotency key, expires_at, ledger entry IDs, timestamps. Transaction reserve khóa account hoặc dùng serializable/atomic constraint để tránh overspend.

### webhook_inbox

<code>id</code>, provider, provider event ID, event type, signature verified timestamp, received_at, status, attempts, payload JSONB hoặc encrypted object reference, error code, processed_at. Unique <code>(provider, provider_event_id)</code>.

## 11. AI, background work và integration

### prompt_versions

<code>id</code>, purpose, version, status draft/active/retired, template/config JSONB, output schema version, created/published actor/time. Unique purpose/version; active transition được audit.

### model_runs

<code>id</code>, user/resource, purpose, provider, model, prompt version ID, request/response schema versions, provider request ID, status, input/output artifact references hoặc redacted hashes, tokens/audio/search usage, estimated cost minor/currency, latency, error code, timestamps.

Không lưu prompt chứa PII đầy đủ trong log table nếu artifact policy không cho phép.

### background_jobs

<code>id</code>, type, queue, resource, status, priority, attempt/max attempts, idempotency key, scheduled/started/finished times, heartbeat, error code, safe payload/result JSONB. Unique type/idempotency key.

### outbox_events

Append-only: <code>id</code>, aggregate type/ID, event type, payload JSONB, correlation ID, occurred_at, published_at, attempts. Index unpublished occurred_at. Publisher dùng skip locked và idempotent consumer.

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
