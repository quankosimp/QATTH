# Changelog

Tất cả thay đổi đáng chú ý của QATTH được ghi lại trong file này.

Định dạng dựa trên [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) và version sản phẩm tuân theo [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Version tài liệu contract có thể mang hậu tố <code>-draft</code> cho đến khi đủ điều kiện phát hành.

## [Unreleased]

### Added

- Bộ requirements có ID ổn định cho Product v1.
- Kiến trúc mục tiêu tách API, worker, PostgreSQL/pgvector, Redis và object storage.
- OpenAPI 3.1 contract mục tiêu với trạng thái implementation trên từng operation.
- Logical database schema cho CV, interview, jobs, recommendation, billing và operations.
- Production runtime handoff và Architecture Decision Records.

### Changed

- Định vị repository từ backend demo sang nền tảng hỗ trợ nghề nghiệp cho sinh viên IT.
- Chuẩn hóa ranh giới sử dụng OpenAI và Gemini Live.
- Chuẩn hóa luồng CV thành draft để người dùng chỉnh sửa và xác nhận trước khi lưu bản chính thức.

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
