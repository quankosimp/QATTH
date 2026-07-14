# Contributing to QATTH

Tài liệu này quy định cách thay đổi backend Product v1 để code, requirement, API, database và bằng chứng vận hành không lệch nhau.

## Nguyên tắc

- Product requirement là nguồn xác định hành vi mong muốn.
- OpenAPI là contract giữa backend và client.
- Database migration là lịch sử bất biến; không sửa migration đã chạy ở môi trường chia sẻ.
- AI output luôn không tin cậy cho đến khi validate bằng schema và business rules.
- Không commit secret, CV thật, transcript thật hoặc dữ liệu nhận diện cá nhân.
- Thay đổi phải nhỏ, có mục đích rõ và có thể rollback.

## Branch và commit

Tạo branch theo một trong các mẫu:

~~~text
feature/<short-description>
fix/<short-description>
docs/<short-description>
refactor/<short-description>
~~~

Commit nên dùng dạng imperative, giới hạn một concern chính:

~~~text
feat: add CV draft confirmation
fix: make credit reservation idempotent
docs: define job discovery data flow
~~~

Không dùng <code>git add -A</code> khi worktree có thay đổi không liên quan. Stage file cụ thể và không rewrite lịch sử branch dùng chung nếu chưa thống nhất.

## Quy trình thay đổi sản phẩm

1. Xác định requirement ID bị tác động trong <code>docs/requirements/</code>.
2. Cập nhật hoặc bổ sung acceptance criteria.
3. Cập nhật <code>docs/api/openapi.yaml</code> nếu interface thay đổi.
4. Cập nhật <code>docs/database/schema.md</code> và tạo migration nếu dữ liệu thay đổi.
5. Implement business logic và provider adapter.
6. Bổ sung unit, integration, contract hoặc migration test phù hợp.
7. Cập nhật observability, runbook và <code>CHANGELOG.md</code> nếu thay đổi đáng chú ý.
8. Chuyển <code>x-implementation-status</code> khi implementation thực tế đáp ứng contract.

## Quản trị requirement

Requirement ID có dạng:

~~~text
FR-<DOMAIN>-<NNN>
NFR-<DOMAIN>-<NNN>
~~~

Ví dụ: <code>FR-CV-003</code>, <code>NFR-PERF-002</code>.

Quy tắc:

- ID đã merge không được tái sử dụng cho ý nghĩa khác.
- Requirement bị loại bỏ phải đánh dấu Deprecated và liên kết quyết định thay thế.
- Mỗi requirement phải có mô tả kiểm thử được.
- Pull request phải nêu requirement ID được implement hoặc thay đổi.
- NFR phải có chỉ số, phạm vi đo và điều kiện loại trừ rõ ràng.

## Quản trị OpenAPI

[docs/api/openapi.yaml](docs/api/openapi.yaml) là contract đã commit được đồng bộ từ FastAPI runtime. Metadata sản phẩm như requirement ID, scope, mô tả và trạng thái được giữ bởi <code>scripts/sync_openapi.py</code>.

Mỗi operation phải có:

- <code>operationId</code> duy nhất.
- <code>x-implementation-status</code>: <code>implemented</code>, <code>partial</code> hoặc <code>planned</code>.
- Security requirement hoặc mô tả rõ vì sao public.
- Success response và error envelope chuẩn.
- Request/response schema không dùng object tự do nếu có thể định nghĩa được.
- <code>Idempotency-Key</code> cho operation tài chính hoặc side effect cần retry an toàn.
- Requirement ID trong <code>x-requirement-ids</code>.

Breaking change cần version mới hoặc migration window. Không xóa field đang được client sử dụng chỉ vì backend không còn cần field đó.

Sau khi thay đổi route/schema, chạy:

~~~bash
PYTHONPATH=backend .venv/bin/python scripts/sync_openapi.py
PYTHONPATH=backend .venv/bin/python scripts/sync_openapi.py --check
~~~

Review phần metadata được giữ trong script trước khi commit endpoint mới; contract test sẽ từ chối runtime operation thiếu requirement ID.

## Database và migration

- PostgreSQL là system of record.
- Dùng quan hệ và constraint cho invariant cốt lõi; JSONB dành cho payload linh hoạt/versioned.
- PDF/raw artifact nằm ở object storage; database lưu object key, checksum, size, content type và ownership.
- Embedding dùng kiểu <code>vector</code> của pgvector với dimension cố định theo embedding model/version.
- Money/credit dùng integer minor unit hoặc integer credit, không dùng float.
- Ledger tài chính là append-only.
- Consumer của queue, webhook và outbox phải idempotent.
- Migration hỗ trợ rollout theo thứ tự expand, migrate/backfill, contract khi có thay đổi breaking.

Pull request database phải nêu forward migration, ảnh hưởng lock/index/backfill, rollback hoặc roll-forward và test migration.

## AI và provider

OpenAI được dùng cho structured extraction, text evaluation, embeddings, web search, ranking support và explanation. Gemini Live được dùng cho voice interview realtime.

Mọi call quan trọng phải:

- Đi qua provider adapter, không rải SDK call trong domain logic.
- Có timeout, retry giới hạn và circuit-breaker/fallback phù hợp.
- Validate structured output.
- Lưu model, prompt version, request correlation, latency, token/cost và outcome.
- Redact secret và hạn chế PII trong log.
- Không coi provider response là source of truth cho job status.
- Gắn citation/source URL cho dữ liệu tìm từ web.

Thay model hoặc prompt ảnh hưởng chất lượng cần evaluation dataset, tiêu chí chấp nhận và ADR nếu đổi ranh giới kiến trúc.

## Security và privacy

- Authentication không đồng nghĩa authorization; kiểm tra ownership và scope tại resource.
- Admin action phải audit.
- Signed URL có TTL ngắn và giới hạn object/method.
- File upload phải kiểm tra content type, size, checksum và malware policy.
- Secret chỉ đi qua environment/secret manager.
- Log không chứa access token, API key, CV text đầy đủ hoặc transcript đầy đủ.
- Export/deletion bao phủ database, object storage, cache và derived data theo retention policy.
- Consent cho product operation và consent cho model training là hai mục đích độc lập.

## Kiểm thử

Các lớp test tối thiểu:

- Unit test cho domain rules, state transition, scoring và credit ledger.
- API contract test cho status code, schema, auth, pagination và idempotency.
- Integration test với PostgreSQL/pgvector, Redis và object storage emulator khi cần.
- Provider adapter test bằng fixture/mock; không gọi API trả phí trong test mặc định.
- Migration test.
- Security test cho object ownership, role/scope và rate limit.
- Load test riêng cho REST, SSE và WebSocket interview.
- AI evaluation cho extraction accuracy, interview consistency, retrieval relevance và citation validity.

Lệnh local hiện tại:

~~~bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests
PYTHONPATH=backend .venv/bin/python scripts/sync_openapi.py --check
~~~

Không cập nhật snapshot/fixture chỉ để làm test xanh nếu chưa xác nhận hành vi mới là đúng.

## Pull request checklist

- Scope, lý do và requirement ID được mô tả.
- OpenAPI và schema docs được cập nhật nếu cần.
- Migration và backward compatibility được xem xét.
- Test phù hợp được thêm/chạy.
- Security, privacy và AI cost được xem xét.
- Metrics/log/trace và failure mode được xem xét.
- Changelog được cập nhật nếu có user/developer impact.
- Không chứa secret hoặc dữ liệu người dùng thật.

## Definition of Done

Một tính năng chỉ hoàn thành khi acceptance criteria đạt, contract và implementation nhất quán, migration an toàn, retry không tạo duplicate side effect, test chính pass, observability đủ điều tra lỗi, dữ liệu nhạy cảm được bảo vệ, provider có cost/rate limit và [traceability matrix](docs/requirements/traceability.md) phản ánh đúng bằng chứng thực tế.

## Phân chia trách nhiệm triển khai

Backend team cung cấp image, migration command, configuration contract, health/readiness và runtime runbook. Deployment team sở hữu hạ tầng cloud, secret injection, CI/CD, DNS/TLS, rollout, backup execution và incident platform.
