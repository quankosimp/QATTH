# Data Flow

## 1. Quy ước chung

- API trả <code>202 Accepted</code> cho tác vụ dài.
- Mọi flow mang <code>request_id</code>; async resource có <code>run_id</code> hoặc <code>job_id</code>.
- Client retry side effect dùng <code>Idempotency-Key</code>.
- PostgreSQL commit business state cùng outbox event; publisher chuyển outbox sang queue.
- Provider payload được giảm thiểu PII và output phải validate trước khi dùng.
- Diagram thể hiện logical flow, không khóa framework triển khai.

## 2. Upload, scan, edit và confirm CV

~~~mermaid
sequenceDiagram
    actor U as Candidate
    participant C as Client
    participant A as API
    participant R2 as R2
    participant DB as PostgreSQL
    participant W as CV Worker
    participant O as OpenAI

    U->>C: Chọn PDF
    C->>A: POST /v1/files/upload-intents
    A->>DB: Tạo file_asset pending
    A-->>C: signed PUT + file_asset_id
    C->>R2: PUT PDF
    C->>A: POST /v1/files/{id}/complete
    A->>R2: HEAD/check metadata
    A->>DB: Mark uploaded/security pending
    C->>A: POST /v1/cv-scans
    A->>DB: Tạo scan queued + outbox
    A-->>C: 202 + scan status URL
    W->>R2: Đọc PDF đã approved
    W->>O: Structured extraction
    O-->>W: JSON candidate
    W->>W: Schema/business validation
    W->>DB: Lưu scan artifact + editable draft
    C->>A: GET/PATCH draft
    A->>DB: Optimistic concurrency update
    U->>C: Xác nhận
    C->>A: POST /v1/cv-drafts/{id}/confirm
    A->>DB: Transaction tạo immutable cv_version + activate
    A-->>C: Confirmed CV version
~~~

Invariant:

- Object phải thuộc user và hoàn tất kiểm tra trước scan.
- Model output không ghi trực tiếp vào active CV.
- Patch draft yêu cầu version/ETag để tránh ghi đè.
- Confirm idempotent và tạo version bất biến.
- Scan attempt, model run và user edit có provenance riêng.

Failure:

- Invalid PDF chuyển file/scan sang error có code ổn định.
- Provider timeout retry hữu hạn; hết retry giữ draft cũ nếu có.
- Confirm conflict trả version conflict, không merge âm thầm.

## 3. Realtime interview và evaluation

~~~mermaid
sequenceDiagram
    actor U as Candidate
    participant C as Client
    participant A as API/Gateway
    participant DB as PostgreSQL
    participant G as Gemini Live
    participant W as Evaluation Worker
    participant O as OpenAI

    C->>A: POST /v1/interviews
    A->>DB: Snapshot CV/preference/job + create session
    A-->>C: interview_id
    C->>A: POST /v1/interviews/{id}/realtime-token
    A-->>C: scoped short-lived token
    C->>A: WebSocket connect
    A->>G: Start Live session
    loop Voice turns
        C->>A: Audio/control event
        A->>G: Relay event
        G-->>A: Audio/transcript event
        A->>DB: Persist ordered event/transcript
        A-->>C: Audio/transcript/status
    end
    C->>A: End interview
    A->>G: Close session
    A->>DB: ending -> evaluating + outbox
    W->>DB: Load transcript/rubric snapshot
    W->>O: Structured evaluation
    O-->>W: Scores + evidence + actions
    W->>DB: Persist report and complete
    C->>A: GET report or receive status event
~~~

Invariant:

- Gateway xác minh ownership trước token và WebSocket upgrade.
- Sequence ID deduplicate event khi reconnect.
- Report tham chiếu transcript/rubric/model version.
- LLM evidence chỉ tham chiếu turn/event tồn tại.
- Evaluation retry không tạo nhiều active report cho cùng version.

Degradation:

- Gemini unavailable: không trừ/settle toàn bộ credit; trả retryable status.
- Client disconnect: giữ session trong reconnect window.
- Evaluation unavailable: interview vẫn giữ transcript và chuyển evaluation_failed để retry.

## 4. Hybrid job discovery

~~~mermaid
sequenceDiagram
    actor U as Candidate
    participant C as Client
    participant A as API
    participant DB as PostgreSQL/pgvector
    participant W as Discovery Worker
    participant O as OpenAI Web Search
    participant J as Job websites
    participant E as Embedding/Ranking
    participant S as SSE

    C->>A: POST /v1/job-search-runs
    A->>DB: Snapshot query/profile + create run
    A-->>C: 202 + run/event URLs
    C->>S: Connect SSE
    W->>DB: FTS + filters + vector top-K
    W->>O: Live web search when requested/needed
    O-->>W: Search calls + URLs/citations/full source list
    W->>J: Safe fetch/HEAD and verify
    J-->>W: JD/status
    W->>DB: Normalize, deduplicate, snapshot, freshness
    W->>E: Embed missing jobs + fuse/rerank
    E-->>W: Ranked top-K + score breakdown
    W->>O: Explain top-N only
    O-->>W: Evidence-grounded explanations
    W->>DB: Persist results/model runs
    W-->>S: progress/result/completed events
    S-->>C: Incremental results
~~~

Retrieval policy:

- Indexed search luôn chạy được khi web provider degraded.
- Live web search bổ sung freshness/coverage, không thay PostgreSQL.
- Source URL phải qua allow/deny policy, redirect limit và safe parser.
- Structured provider output phải qua local schema/business validation; source URL không có provider evidence bị loại.
- Job active là trạng thái xác minh có thời hạn, không phải claim của LLM.
- Trang không phải HTML, hết hạn hoặc không khớp title/company được lưu rejection outcome và không xuất hiện trong live results.
- Dedup giữ tất cả source references và raw snapshots.
- Hard filter không do LLM quyết định.
- Explanation chỉ chạy top-N để giảm cost và hallucination.

SSE event tối thiểu:

- <code>run.started</code>
- <code>source.progress</code>
- <code>job.discovered</code>
- <code>job.verified</code>
- <code>job.rejected</code>
- <code>results.updated</code>
- <code>run.completed</code>
- <code>run.failed</code>

Client reconnect bằng <code>Last-Event-ID</code>; nếu event buffer hết hạn, client lấy snapshot từ status/results endpoint.

## 5. Credit reservation, settlement và webhook

~~~mermaid
sequenceDiagram
    actor U as Candidate
    participant C as Client
    participant A as API
    participant DB as PostgreSQL
    participant W as Worker
    participant P as AI/Payment Provider

    C->>A: Start paid action + Idempotency-Key
    A->>DB: Transaction lock account, check entitlement, reserve credit
    A-->>C: 202 + action ID
    W->>P: Execute provider action
    alt Success
        P-->>W: Usage/result
        W->>DB: Transaction settle reservation + post ledger
    else Retryable failure
        P-->>W: Error
        W->>DB: Keep reservation until retry deadline
    else Terminal failure
        W->>DB: Release reservation + ledger/audit
    end
~~~

Payment webhook:

1. API đọc raw body và xác minh signature/timestamp.
2. Insert webhook inbox theo unique provider/event ID.
3. Duplicate trả success an toàn nhưng không xử lý lại.
4. Worker normalize event.
5. Transaction cập nhật subscription projection, entitlement và credit ledger.
6. Mark inbox processed hoặc failed có retry.
7. Reconciliation so sánh event/provider state định kỳ.

Không tính balance bằng cache. Redis chỉ cache projection có thể rebuild.

## 6. Privacy export và deletion

~~~mermaid
sequenceDiagram
    actor U as Candidate
    participant A as API
    participant DB as PostgreSQL
    participant W as Privacy Worker
    participant R2 as R2

    U->>A: Request export/deletion
    A->>DB: Verify identity, create privacy request
    A-->>U: 202 + status
    W->>DB: Lock/checkpoint request
    alt Export
        W->>DB: Read allowed domain data
        W->>R2: Write encrypted archive
        W->>DB: Store expiring artifact metadata
        A-->>U: Short-lived download URL
    else Deletion
        W->>DB: Revoke sessions, stop processing
        W->>R2: Delete owned artifacts
        W->>DB: Delete/anonymize domain data
        W->>DB: Keep minimal legal/audit tombstone
    end
~~~

Deletion phải liệt kê exception retention, retry object deletion và không báo complete trước khi mọi checkpoint bắt buộc thành công. Backup data hết hạn theo backup lifecycle thay vì sửa backup lịch sử.

## 7. Observability flow

- Edge nhận hoặc tạo request ID và API chuẩn hóa.
- API tạo trace span, redacts query và không gắn CV/transcript/email/token; request ID được giữ riêng để điều tra.
- Outbox chứa correlation context tối thiểu.
- Celery tự inject/extract W3C trace context; worker tiếp tục trace và vẫn giữ request ID trong durable run/outbox.
- Provider request ID/model usage lưu trong model run.
- Structured log chỉ ghi identifier và error code an toàn.
- Metric label không dùng user ID, job ID hoặc URL làm high-cardinality dimension.
- Audit event tách khỏi application log và không bị sampling.

## 8. Data lineage

| Output | Input lineage bắt buộc |
|---|---|
| CV version | file asset, scan attempt, draft revision, schema/model/prompt version, confirmer |
| CV analysis | CV version, rubric/prompt/model version |
| Interview report | interview session, transcript version, CV/job snapshot, rubric/model version |
| Job posting | source, source URL/ID, raw snapshot, normalized version, checked_at |
| Match result | candidate profile version, job snapshot, retrieval/ranker version |
| Explanation | match result, candidate/job evidence, prompt/model version |
| Credit ledger entry | reservation/action/webhook/admin reference và idempotency key |
