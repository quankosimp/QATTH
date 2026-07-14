# Changelog

Tất cả thay đổi đáng chú ý của QATTH được ghi lại trong file này.

Định dạng dựa trên [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) và version sản phẩm tuân theo [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Version tài liệu contract có thể mang hậu tố <code>-draft</code> cho đến khi đủ điều kiện phát hành.

## [Unreleased]

### Added
- Append-only recommendation feedback events with server-derived run, rank, score, experiment and training-consent attribution.
- Scheduled Paddle checkout/subscription reconciliation, stuck inbox recovery and payment payload retention enforcement.
- Paddle production billing adapter với checkout, customer portal, replay-safe webhook normalization và server-side offer mapping.
- Live job discovery hardening với full OpenAI source provenance, local schema validation, domain policy và active-page verification.
- Gemini Live realtime hardening với distributed session lease, reconnect/resumption, context compression, duration/idle limits và usage lineage.
- Backend Product v1 cho identity/profile/consent, file/CV lifecycle, interview, job discovery, recommendation, billing, privacy, administration và operations.
- Migration chain cho các domain Product v1 và các hardening revision về identity, interview, job search, billing dual-control và provider usage.
- Provider resilience gồm timeout, retry jitter, circuit breaker, bulkhead, usage/cost ledger và budget guardrail.
- Đặc tả hybrid subscription, top-up, signup trial, bucketed credits và provider-neutral payment.
- Bộ requirements có ID ổn định cho Product v1.
- Kiến trúc mục tiêu tách API, worker, PostgreSQL/pgvector, Redis và object storage.
- OpenAPI 3.1 đồng bộ từ FastAPI runtime, giữ requirement metadata và có contract drift test.
- Logical database schema cho CV, interview, jobs, recommendation, billing và operations.
- Production runtime handoff và Architecture Decision Records.
- Requirement traceability matrix và kịch bản k6 cho smoke/load/stress test.

### Changed

- Job ingest now rechecks allow/block policy before fetch and after redirects, and rejects admin-disabled sources before persistence.
- Distributed rate limiting now uses atomic Redis Lua buckets for trusted client IP, principal and normalized action, with lower AI-cost quotas and production fail-closed behavior.
- Production startup now fails fast when malware scanning, privacy encryption or Paddle configuration is missing or insecure.
- Verified PDF uploads are promoted from expiring staging keys to server-only clean keys, preventing a still-valid upload URL from replacing content after malware scanning.
- Product workers, payment inboxes and dispatch outboxes now persist only bounded error codes and fixed safe messages; validation and unhandled error boundaries omit submitted values and exception text.
- Job search, recommendation and privacy runs now persist the originating correlation ID and propagate it through Celery headers during immediate publish or later outbox recovery.
- Production readiness now rejects incompatible database revisions and unavailable Redis, queue, private object storage or malware-scanner dependencies; startup also enforces the schema revision gate.
- Interview credits are reserved at realtime token issuance and captured only after the first successful Gemini output delivery; timeout reconciliation now follows CV/interview outcomes.
- Client checkout redirect URLs are retained only by QATTH and are no longer copied into provider metadata.
- Payment reversal dùng provider transaction reference, hỗ trợ partial reversal và chỉ đưa account vào review khi phát sinh debt.
- Định vị repository từ backend demo sang backend Product v1 của nền tảng hỗ trợ nghề nghiệp cho sinh viên IT.
- Chuẩn hóa ranh giới sử dụng OpenAI và Gemini Live.
- Chuẩn hóa luồng CV thành draft để người dùng chỉnh sửa và xác nhận trước khi lưu bản chính thức.
- Tắt legacy API mặc định; Product API sử dụng namespace <code>/v1</code> và import root <code>app.*</code> thống nhất.

## [0.1.0] - 2026-07-14

### Added

- FastAPI backend demo.
- Luồng authentication, profile và consent cơ bản.
- Upload/scan CV, lưu CV record và version.
- Interview session, turn/transcript và evaluation cơ bản.
- Candidate discovery, job ingestion/search, matching và recommendation thử nghiệm.
- Background task, audit, model run và operations endpoint.
- Docker Compose cho local với PostgreSQL/pgvector, Redis và object storage tương thích S3.

[Unreleased]: https://github.com/quankosimp/QATTH/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/quankosimp/QATTH/releases/tag/v0.1.0
