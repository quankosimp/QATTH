# Load and Stress Testing

## 1. Mục tiêu

Load test xác nhận NFR-PERF-001..008 và failure mode, không dùng để tạo traffic vào API trả phí hoặc dữ liệu người dùng thật. Script chuẩn nằm tại <code>tests/load/product_api.js</code> và dùng k6.

Phân biệt workload:

- **Smoke:** 1-2 virtual users, xác nhận script/environment.
- **Load:** tải pilot dự kiến trong 15-30 phút để đo percentile ổn định.
- **Stress:** tăng vượt tải pilot để tìm saturation và degradation behavior.
- **Soak:** tải ổn định 2-8 giờ để phát hiện leak, pool exhaustion và queue growth.
- **Spike:** tăng/giảm đột ngột để kiểm tra admission, autoscaling và recovery.

## 2. Chuẩn bị

- Dùng staging cô lập có PostgreSQL/pgvector, Redis, object storage và telemetry tương đương production.
- Seed job catalog không chứa PII, có volume và phân bố filter/embedding được ghi lại.
- Dùng test users/tokens riêng; không dùng production token.
- Mock provider trả phí cho baseline backend; chạy provider staging test trong budget/cửa sổ riêng.
- Ghi image digest, migration head, resource limits, replica/concurrency, pool size và feature flags.

## 3. Chạy k6

Smoke public health:

~~~bash
k6 run -e BASE_URL=http://localhost:8000 tests/load/product_api.js
~~~

Authenticated read load:

~~~bash
k6 run \
  -e BASE_URL=https://staging-api.example.com \
  -e ACCESS_TOKEN="$ACCESS_TOKEN" \
  -e AUTH_READ_PATH=/v1/users/me \
  -e AUTH_VUS=50 \
  -e DURATION=15m \
  tests/load/product_api.js
~~~

Stress ramp:

~~~bash
k6 run \
  -e BASE_URL=https://staging-api.example.com \
  -e ACCESS_TOKEN="$ACCESS_TOKEN" \
  -e STRESS=true \
  -e AUTH_READ_PATH=/v1/users/me \
  tests/load/product_api.js
~~~

Kịch bản write/search phải dùng endpoint/body test được release owner cung cấp qua <code>WRITE_PATH</code> và <code>WRITE_BODY</code>. Không bật nếu operation tạo chi phí/provider side effect chưa có quota test.

## 4. Voice và async workload

REST load không chứng minh NFR-PERF-006/007. Voice test phải bổ sung harness gửi audio fixture hợp lệ qua WebSocket, đo time-to-first-audio, reconnect, sequence duplication và transcript loss ở 20 session đồng thời. CV/search async phải đo riêng API enqueue latency, queue oldest age, completion percentile và provider latency; không gộp thời gian provider vào REST write latency.

## 5. Acceptance và báo cáo

- Đối chiếu threshold trong non-functional requirements, không thay threshold sau khi thấy kết quả nếu chưa có risk acceptance.
- Báo cáo p50/p95/p99, throughput, error rate theo safe error code, saturation CPU/memory/pool/queue và recovery time.
- Mọi HTTP <code>429</code> có chủ đích phải báo riêng với retry metadata; không gộp thành provider failure.
- Xác nhận không có duplicate CV version, interview completion, application event hoặc credit mutation sau retry/stress.
- Lưu summary/trend output ngoài repository nếu chứa hostname/token; commit báo cáo đã redact hoặc link artifact theo release.

Chỉ sau khi report đạt threshold trong đúng môi trường pilot mới cập nhật các dòng NFR-PERF từ Evidence pending.
