# ADR 0002: Use OpenAI for Structured AI and Web Discovery, Gemini Live for Voice

- Status: Accepted
- Date: 2026-07-14
- Decision owners: Backend architecture and AI product
- Related requirements: FR-CV-002, FR-INT-003, FR-INT-006, FR-JOB-002, FR-JOB-008, NFR-AI-001

## Context

Product v1 cần các năng lực AI khác nhau:

- Trích xuất CV PDF/text thành JSON theo schema.
- Phân tích CV.
- Đánh giá transcript phỏng vấn theo rubric và evidence.
- Tạo embedding cho candidate/job.
- Tìm job mới trên Internet.
- Giải thích top match dựa trên evidence.
- Hội thoại giọng nói realtime.

Demo cũ dùng provider theo cách thử nghiệm và chưa có ranh giới adapter, model run audit, cost control hay evaluation đầy đủ. Product thật cần giảm số integration cho tác vụ text/search nhưng voice realtime vẫn cần trải nghiệm đã chọn với Gemini Live.

## Decision

Dùng OpenAI API làm provider mặc định cho:

- Structured CV extraction.
- CV/interview text analysis và structured evaluation.
- Embeddings.
- Web search để discovery job URL/content.
- Rerank support khi feature/rubric yêu cầu.
- Grounded explanation cho một số kết quả đầu.

Dùng Gemini Live API cho phỏng vấn giọng nói realtime.

Domain code chỉ gọi internal ports/adapters. Model cụ thể là runtime configuration có version, không hard-code trong business logic. Provider output không phải canonical truth:

- CV output tạo editable draft.
- Web search output tạo job candidate có citation, sau đó URL verification/normalization quyết định trạng thái.
- Interview evaluation phải trích evidence từ transcript.
- Explanation không thay đổi hard filter hoặc rank đã persist.

## Why

- Gom structured text, embeddings và web discovery vào một provider giúp giảm integration surface ở Product v1.
- Structured output phù hợp với requirement validate JSON trước canonicalization.
- Web search từ cùng API tránh phải bắt buộc thêm Firecrawl chỉ để discovery.
- Gemini Live được giữ cho voice vì đó là ranh giới realtime riêng và đã nằm trong product direction.
- Adapter cho phép thay provider/model nếu quality, cost, availability hoặc policy thay đổi.

Quyết định này không đồng nghĩa mọi website cho phép crawl hoặc mọi kết quả search đều active. QATTH vẫn chịu trách nhiệm access policy, safe fetch, provenance, freshness và deduplication.

## Alternatives considered

### Gemini for all AI tasks

Ưu điểm là một provider và demo đã có kinh nghiệm. Không chọn vì product direction muốn OpenAI cho structured/search/embedding và tách Gemini Live theo năng lực voice. Provider adapter vẫn cho phép benchmark/fallback sau.

### OpenAI for realtime voice as well

Ưu điểm là một provider duy nhất. Không chọn trong Product v1 vì Gemini Live đã là lựa chọn cho phòng phỏng vấn. Có thể đánh giá lại bằng latency, quality, cost và operational data.

### Firecrawl or crawler platform as mandatory discovery layer

Ưu điểm là fetch/render/extraction chuyên biệt. Không chọn làm dependency bắt buộc ban đầu vì OpenAI web search có thể discovery và trích citation. Tuy nhiên web search không thay safe URL verification/parser. Có thể bổ sung crawler adapter cho nguồn được phép khi cần full JD/rendering đáng tin cậy.

### Self-hosted/open-source models

Ưu điểm là kiểm soát dữ liệu và unit cost ở scale lớn. Không chọn cho Product v1 vì GPU operations, evaluation, latency và model maintenance tăng đáng kể. Adapter giữ khả năng thử nghiệm sau.

### LLM-only job ranking

Không chọn vì cost, latency, non-determinism và hallucination. PostgreSQL FTS/pgvector/filter tạo candidates; versioned reranker xếp hạng; LLM chỉ giải thích top-N hoặc hỗ trợ feature có kiểm soát.

## Provider boundary

Adapter phải cung cấp interface theo purpose thay vì expose SDK:

- extract CV theo schema version.
- analyze CV theo rubric version.
- evaluate interview theo transcript/rubric.
- embed batch theo embedding version/dimension.
- web search theo query/filter/budget.
- explain matches từ evidence đã chọn.
- create/relay Gemini Live session.

Mỗi call lưu hoặc liên kết:

- provider, model và configuration version.
- prompt/rubric/output schema version.
- request/correlation và provider request ID.
- latency, token/audio/search usage và estimated cost.
- status, retry count và safe error code.
- input/output hash hoặc artifact reference theo privacy policy.

## Safety and privacy controls

- Chỉ gửi subset dữ liệu cần cho purpose.
- Không gửi secret, internal authorization hoặc credit data vào prompt.
- Redact log và không log CV/transcript đầy đủ.
- Tách consent product processing khỏi model training.
- Structured response phải qua JSON Schema và business validation.
- Nội dung job/web được coi là untrusted input và cách ly khỏi system instruction.
- Citation URL qua allow/deny policy, redirect limit, SSRF protection và verification.
- Không cho model tự gọi URL nội bộ hoặc arbitrary tool.
- AI score có disclaimer và không dùng quyết định tuyển dụng tự động.

## Reliability and cost controls

- Timeout hữu hạn theo task.
- Retry chỉ với lỗi transient, exponential backoff + jitter.
- Circuit breaker/bulkhead theo provider/purpose.
- Queue isolation và admission control.
- Per-user/action quota và credit reservation.
- Daily/monthly provider budget và alert.
- Cache embedding theo content hash/model version.
- Batch embedding khi phù hợp.
- LLM explanation chỉ top-N.
- Indexed search/evidence vẫn dùng được khi web search/explanation degraded.
- Evaluation failure không làm mất CV draft/transcript đã persist.

## Quality gates

Trước khi activate model/prompt version mới:

1. Chạy offline dataset versioned cho CV tiếng Việt/Anh.
2. Đo schema-valid rate và field-level extraction quality.
3. Đo interview rubric consistency và evidence validity.
4. Đo job retrieval relevance, live citation validity và stale rate.
5. Đo explanation groundedness.
6. So sánh latency và cost với baseline.
7. Canary theo tỷ lệ nhỏ.
8. Giữ khả năng activate version cũ.

Không đổi model chỉ dựa trên benchmark chung; phải dùng workload QATTH.

## Consequences

Positive:

- Ranh giới provider rõ cho backend.
- Giảm số integration text/search ở Product v1.
- Có structured validation, provenance và cost accounting thống nhất.
- Voice failure được cô lập khỏi batch text pipeline.
- Có đường thay model/provider qua adapter.

Negative:

- Hai AI provider vẫn làm tăng secret, observability, incident và billing complexity.
- External API outage/rate limit ảnh hưởng core flow.
- Chi phí có thể biến động và cần quota/credit.
- Web result cần verification riêng; OpenAI không thay crawler/parser hoàn toàn.
- Data transfer/privacy review là bắt buộc.
- Model behavior thay đổi đòi hỏi evaluation và version pin/config.

## Implementation status

Decision đã accepted nhưng implementation production còn pending. Demo không được xem là tuân thủ ADR cho đến khi có adapter, model run audit, structured validation, evaluation suite, privacy control, timeout/retry, cost guardrail và degraded behavior.

## Revisit triggers

- Gemini Live hoặc OpenAI không đạt SLO/quality/cost sau tuning.
- Provider policy/retention không đáp ứng privacy requirement.
- OpenAI web search coverage/citation không đủ cho nguồn mục tiêu.
- Scale làm self-host hoặc provider khác kinh tế hơn.
- Realtime architecture cần multi-provider failover.
- Regulatory/customer requirement buộc region hoặc deployment model khác.

Thay provider mặc định hoặc thay ranh giới voice/text cần ADR mới, migration model configuration và quality comparison.
