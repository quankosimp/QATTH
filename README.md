# QATTH

QATTH là nền tảng hỗ trợ sinh viên IT chuyển CV thành hồ sơ nghề nghiệp có cấu trúc, luyện phỏng vấn với AI và tìm việc làm phù hợp còn hiệu lực trên Internet.

Sản phẩm tạo một vòng lặp hoàn chỉnh:

1. Sinh viên tải CV lên.
2. AI trích xuất CV thành dữ liệu có cấu trúc.
3. Sinh viên kiểm tra, chỉnh sửa và xác nhận trước khi lưu.
4. Phòng phỏng vấn AI được cá nhân hóa theo CV và mục tiêu nghề nghiệp.
5. Hệ thống đánh giá buổi phỏng vấn, xác định khoảng trống kỹ năng.
6. Công việc được tìm từ chỉ mục nội bộ và nguồn web còn hiệu lực, sau đó xếp hạng theo mức độ phù hợp.
7. Người dùng nhận giải thích, JD, nguồn gốc và theo dõi quá trình ứng tuyển.

## Trạng thái sản phẩm

Repository hiện chứa backend demo đã chạy được và bộ tài liệu Product v1 định hướng quá trình refactor thành sản phẩm production.

| Phạm vi | Hiện tại | Đích Product v1 |
|---|---|---|
| CV | Upload, scan, lưu phiên bản | Draft có cấu trúc, người dùng duyệt, lịch sử phiên bản, phân tích có truy vết |
| Phỏng vấn | Session và transcript cơ bản | Gemini Live realtime, event log, evaluation bất đồng bộ, báo cáo |
| Việc làm | Crawl/search và matching thử nghiệm | PostgreSQL FTS + pgvector, OpenAI web search, xác minh URL, deduplicate, rerank |
| AI | Gemini và adapter demo | OpenAI cho text/search/embedding, Gemini Live cho voice, model run audit |
| Dữ liệu | PostgreSQL/SQLite và object storage demo | Managed PostgreSQL + pgvector, R2, Redis |
| Vận hành | Docker Compose local | Container API/worker có health check, migration và observability |
| Thanh toán | Chưa có | Subscription, credit ledger, reservation và webhook idempotent |

Mỗi operation trong [OpenAPI Product v1](docs/api/openapi.yaml) có trường <code>x-implementation-status</code> để phân biệt <code>implemented-demo</code>, <code>partial</code> và <code>planned</code>. Tài liệu mục tiêu không đồng nghĩa toàn bộ endpoint đã tồn tại trong code hiện tại.

## Đối tượng và giá trị

### Sinh viên IT

- Biến CV PDF thành hồ sơ có thể chỉnh sửa thay vì tin hoàn toàn vào kết quả AI.
- Luyện phỏng vấn theo đúng kinh nghiệm, kỹ năng và vị trí mong muốn.
- Hiểu điểm mạnh, điểm yếu và hành động cải thiện cụ thể.
- Tìm việc còn hiệu lực, có JD và đường dẫn nguồn.
- Biết vì sao một công việc phù hợp thay vì chỉ nhận một điểm số.

### Nhóm vận hành sản phẩm

- Quản trị prompt/model version, chi phí AI và hạn mức sử dụng.
- Theo dõi background job, provider failure, search quality và funnel ứng tuyển.
- Xử lý yêu cầu export/xóa dữ liệu và điều tra bằng audit trail.
- Quản lý subscription, credit và webhook theo cơ chế idempotent.

## Kiến trúc mục tiêu

~~~mermaid
flowchart LR
    U[Web/Mobile Client] --> E[Cloudflare CDN/WAF]
    E --> API[Container API]
    API --> PG[(Managed PostgreSQL + pgvector)]
    API --> R[(Redis)]
    API --> R2[(Cloudflare R2)]
    API --> Q[Worker queues]
    Q --> PG
    Q --> R2
    API --> OAI[OpenAI API]
    Q --> OAI
    API <--> GEM[Gemini Live API]
    API --> PAY[Payment provider]
    API --> OBS[Logs / Metrics / Traces]
    Q --> OBS
~~~

Các ranh giới quan trọng:

- PostgreSQL là nguồn dữ liệu nghiệp vụ chính; JSONB dùng cho payload linh hoạt có version, không thay thế schema quan hệ.
- R2 lưu PDF, transcript artifact và raw JD lớn; database chỉ lưu metadata, checksum và object key.
- Redis phục vụ cache, distributed rate limit, coordination và hàng đợi tùy implementation.
- OpenAI xử lý structured extraction, evaluation, embeddings, web search và explanation.
- Gemini Live chỉ chịu trách nhiệm hội thoại giọng nói realtime.
- API không phụ thuộc trực tiếp vào một payment provider; webhook và transaction đi qua adapter nội bộ.

Xem [Architecture Overview](docs/architecture/overview.md).

## Cấu trúc repository

~~~text
.
├── backend/                  # FastAPI backend hiện tại
├── tests/                    # Automated tests
├── scripts/                  # Local/database utilities
├── docs/
│   ├── requirements/         # Functional và non-functional requirements
│   ├── architecture/         # System context, components và data flows
│   ├── api/openapi.yaml      # Product v1 API contract
│   ├── database/schema.md    # Logical schema và migration rules
│   ├── deployment/           # Production runtime handoff
│   └── adr/                  # Architecture Decision Records
├── docker-compose.yml        # Local integration environment
├── CHANGELOG.md
└── CONTRIBUTING.md
~~~

Code hiện vẫn nằm trong <code>backend/</code>. Bộ tài liệu không giả định việc đổi sang <code>src/</code>; thay đổi cấu trúc code phải có ADR/refactor riêng.

## Chạy backend local

Yêu cầu:

- Docker và Docker Compose.
- Hoặc Python theo version khai báo trong [pyproject.toml](pyproject.toml).

Khởi động bằng Docker:

~~~bash
cp .env.example .env
docker compose up --build
~~~

Địa chỉ mặc định:

- API: <code>http://localhost:8000</code>
- Swagger UI: <code>http://localhost:8000/docs</code>
- OpenAPI runtime hiện tại: <code>http://localhost:8000/openapi.json</code>

[docs/api/openapi.yaml](docs/api/openapi.yaml) là contract mục tiêu Product v1; OpenAPI sinh từ backend là hành vi hiện đã implement. Khi refactor, chênh lệch giữa hai contract phải được theo dõi bằng trạng thái implementation và contract tests.

Chạy backend trực tiếp:

~~~bash
uv sync --all-groups
uv run uvicorn backend.app.main:app --reload
~~~

Chạy test và lint:

~~~bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests
~~~

Không commit secret, API key hoặc dữ liệu CV thật vào repository.

## Nguyên tắc API Product v1

- Base path: <code>/v1</code>.
- OIDC JWT cho API người dùng và admin.
- Response envelope nhất quán: <code>data</code>, <code>error</code>, <code>meta</code>.
- <code>X-Request-ID</code> dùng để truy vết xuyên API, worker và provider.
- <code>Idempotency-Key</code> bắt buộc cho operation có side effect nhạy cảm.
- Tác vụ dài trả <code>202 Accepted</code> cùng resource/status URL.
- Cursor pagination thay cho offset ở collection có tăng trưởng lớn.
- WebSocket dành cho voice realtime; SSE dành cho tiến trình search/report một chiều.
- Error code ổn định và tách biệt với message hiển thị.
- Endpoint admin phải có authorization theo role/scope và audit log.

## An toàn dữ liệu và AI

CV, transcript, đánh giá phỏng vấn và lịch sử ứng tuyển là dữ liệu cá nhân nhạy cảm. Product v1 yêu cầu:

- Người dùng xác nhận dữ liệu CV do AI trích xuất trước khi trở thành phiên bản chính thức.
- Kết quả AI quan trọng lưu provider, model, prompt version, latency, token/cost và trạng thái.
- Kết quả job từ web phải có source URL, thời điểm kiểm tra và trạng thái xác minh.
- Không gửi dữ liệu vượt quá mục đích xử lý tới AI provider.
- Có retention policy, export và deletion workflow.
- Không dùng CV/transcript để train model nếu chưa có consent riêng, rõ ràng và có thể thu hồi.
- AI score là tín hiệu hỗ trợ, không phải quyết định tuyển dụng tự động.

## Tài liệu

- [Functional Requirements](docs/requirements/functional-requirements.md)
- [Non-functional Requirements](docs/requirements/non-functional-requirements.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Components](docs/architecture/components.md)
- [Data Flow](docs/architecture/data-flow.md)
- [OpenAPI Product v1](docs/api/openapi.yaml)
- [Database Schema](docs/database/schema.md)
- [Production Runtime](docs/deployment/production.md)
- [ADR 0001: PostgreSQL](docs/adr/0001-use-postgresql.md)
- [ADR 0002: OpenAI API](docs/adr/0002-use-openai-api.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## Phân chia trách nhiệm

Backend team chịu trách nhiệm API contract, business logic, database migrations, Docker image, runtime configuration, health/readiness, worker semantics và observability instrumentation.

Deployment team chịu trách nhiệm provision hạ tầng cloud, DNS, TLS, network, secret injection, CI/CD, rollout/rollback, autoscaling, backup execution và incident platform.

Chi tiết handoff nằm trong [Production Runtime](docs/deployment/production.md).

## Quy trình thay đổi

Mọi thay đổi hành vi phải cập nhật đồng thời requirement liên quan, OpenAPI, schema/migration, test và changelog khi phù hợp. Xem [CONTRIBUTING.md](CONTRIBUTING.md).
