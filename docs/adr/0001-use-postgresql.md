# ADR 0001: Use PostgreSQL as the System of Record

- Status: Accepted
- Date: 2026-07-14
- Decision owners: Backend architecture
- Related requirements: FR-CV-004, FR-JOB-006, FR-BILL-004, NFR-DATA-005

## Context

QATTH cần lưu nhiều kiểu dữ liệu:

- Identity, ownership và consent.
- CV JSON có version và transaction confirm.
- Interview event/report.
- Job normalized, full-text document và embedding.
- Match result có provenance.
- Subscription, credit ledger và webhook idempotency.
- Audit, outbox và privacy workflow.
- PDF/raw artifact lớn.

Các domain này có nhiều quan hệ, invariant đồng thời và yêu cầu truy vết. Job search cũng cần filter, full-text và vector retrieval trên cùng dữ liệu. Cloudflare là nền tảng edge/object phù hợp nhưng không nên buộc core transactional model vào edge database chỉ để đồng nhất nhà cung cấp.

## Decision

Dùng managed PostgreSQL làm system of record cho Product v1.

- Dùng relational table, foreign key, unique/check constraint và transaction cho invariant.
- Dùng JSONB cho payload linh hoạt/versioned như CV content, rubric output và source metadata.
- Dùng PostgreSQL Full Text Search cho lexical retrieval.
- Dùng pgvector cho embedding và semantic retrieval.
- Dùng Cloudflare R2 cho PDF, raw JD và artifact lớn; PostgreSQL lưu metadata/object key/checksum.
- Dùng Redis cho cache, distributed rate limit và ephemeral coordination, không làm source of truth.
- Mọi thay đổi schema đi qua migration được version và review.

## Why

- CV confirm, credit reserve/settle và webhook processing cần transaction/unique constraint rõ.
- FTS + vector + structured filter trong cùng database giảm vận hành thêm search cluster ở quy mô pilot.
- JSONB cho phép tiến hóa AI schema nhưng vẫn giữ ownership/version trong transaction.
- PostgreSQL ecosystem hỗ trợ backup/PITR, observability, migration và đội backend dễ quản trị.
- Thiết kế có thể tách search service sau này nếu volume/chất lượng chứng minh cần thiết.

## Alternatives considered

### Cloudflare D1

Ưu điểm:

- Gần edge và tích hợp Cloudflare.
- Vận hành đơn giản cho workload nhỏ.

Không chọn làm core database vì requirement hiện tại cần PostgreSQL ecosystem, pgvector, transaction/query pattern và migration/observability trưởng thành hơn. D1 có thể phù hợp cho edge metadata/cache riêng, không phải canonical data Product v1.

### MongoDB/document database

Ưu điểm:

- Tự nhiên với CV/job JSON linh hoạt.
- Schema evolution nhanh ở demo.

Không chọn vì nhiều invariant quan hệ và ledger/idempotency cần constraint/transaction; FTS/vector/filter sẽ phân tán logic hoặc tăng hệ thống vận hành. PostgreSQL JSONB đã đáp ứng phần linh hoạt cần thiết.

### Dedicated search engine

Ưu điểm:

- Search feature và horizontal scale chuyên sâu.

Không chọn ở pilot vì thêm pipeline đồng bộ, vận hành và consistency. Có thể bổ sung sau nếu PostgreSQL không đạt benchmark hoặc search requirement vượt khả năng FTS/pgvector.

### Store PDF in database

Ưu điểm là transaction metadata/blob cùng chỗ, nhưng làm backup, IO, retention và egress nặng. R2 phù hợp hơn; checksum/object state giải quyết consistency bằng workflow.

## Consequences

Positive:

- Một transactional source cho domain chính.
- Hybrid FTS/vector không cần thêm search cluster ban đầu.
- Constraint/idempotency/ledger rõ và test được.
- Managed backup/PITR và tooling trưởng thành.

Negative:

- Backend không thể chạy hoàn toàn trên Cloudflare edge.
- Vector index/tuning và connection pool cần chuyên môn.
- JSONB dễ bị lạm dụng nếu không có schema/version/index discipline.
- Live web search vẫn cần provider/pipeline ngoài database.
- Scale cực lớn có thể cần partition, replica hoặc search service.

## Guardrails

- Blob không lưu trong PostgreSQL.
- Embedding dùng kiểu vector thật, không JSON array.
- JSONB không chứa invariant cốt lõi nếu cần constraint/query thường xuyên.
- Index chỉ thêm theo access pattern và query plan.
- API/worker budget connection theo tổng replica.
- Migration theo expand/backfill/contract.
- Credit ledger, audit và event history append-only.
- Benchmark FTS/vector với dataset đại diện trước production.

## Revisit triggers

Xem xét lại khi một trong các điều kiện xảy ra:

- Indexed job corpus/query load không đạt NFR dù đã tuning/scale hợp lý.
- Multi-region write trở thành requirement bắt buộc.
- Vector/search feature cần capability PostgreSQL không đáp ứng.
- Chi phí managed PostgreSQL không phù hợp với usage thực.
- Cloudflare database capability thay đổi và có benchmark/transaction guarantee đáp ứng toàn bộ requirement.

Mọi thay đổi system of record cần ADR mới và migration/dual-write/rollback plan.
