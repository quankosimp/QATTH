# Functional Requirements

## 1. Mục đích

Tài liệu này mô tả hành vi mục tiêu của QATTH Product v1. Đây là nguồn chuẩn cho product scope, API contract, database design và acceptance tests; không phải danh sách những gì demo hiện tại đã implement.

## 2. Quy ước

- Mức ưu tiên: **Must** bắt buộc cho Product v1, **Should** cần có sau khi lõi ổn định, **Could** có thể hoãn.
- Trạng thái: **Target** là contract mục tiêu, **Partial** là demo đã có một phần, **Implemented** chỉ dùng khi có test và vận hành đáp ứng requirement.
- ID đã phát hành không được tái sử dụng.
- Mọi timestamp API dùng UTC theo RFC 3339.
- Người dùng mặc định là sinh viên/candidate; admin và support là privileged roles.

## 3. Identity, access và profile

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-AUTH-001 | Hệ thống phải đăng nhập người dùng qua OIDC/OAuth 2.1 và phát hành session an toàn cho client. | Must | Token hợp lệ tạo/ánh xạ đúng user; token hết hạn hoặc sai issuer/audience bị từ chối; không lưu provider access token dạng plaintext. |
| FR-AUTH-002 | Mọi resource cá nhân phải kiểm tra ownership; endpoint quản trị phải kiểm tra role/scope. | Must | User A không đọc/sửa resource của user B; hành động admin thiếu scope trả lỗi authorization ổn định. |
| FR-AUTH-003 | Người dùng phải xem và thu hồi các session đang hoạt động. | Should | Thu hồi session làm token/session tương ứng mất hiệu lực trong thời gian propagation đã công bố. |
| FR-AUTH-004 | Hệ thống phải hỗ trợ khóa tài khoản và vô hiệu hóa access khi phát hiện abuse. | Must | Tài khoản bị khóa không tạo session mới; session cũ bị revoke; hành động được audit. |
| FR-PROFILE-001 | Người dùng phải tạo và cập nhật hồ sơ nghề nghiệp gồm headline, location, seniority, links và kỹ năng. | Must | Field được validate; thay đổi được lưu với updated timestamp; URL nguy hiểm bị từ chối. |
| FR-PROFILE-002 | Người dùng phải cấu hình job preference gồm role, location, remote mode, salary, employment type và kỹ năng ưu tiên. | Must | Preference có thể cập nhật độc lập với CV; matching run mới dùng snapshot preference mới nhất. |
| FR-PROFILE-003 | Hệ thống phải lưu consent theo purpose và version chính sách. | Must | Có granted/withdrawn timestamp; consent bắt buộc được kiểm tra trước xử lý; training consent tách khỏi product-processing consent. |

## 4. File và CV lifecycle

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-FILE-001 | Client phải lấy upload intent/signed URL trước khi gửi PDF trực tiếp tới object storage. | Must | Intent bị ràng buộc user, content type, size và TTL; complete request kiểm tra object metadata/checksum. |
| FR-FILE-002 | Hệ thống phải kiểm tra loại file, kích thước, checksum và trạng thái malware trước khi scan. | Must | File không hợp lệ hoặc chưa đạt security status không được chuyển sang pipeline CV. |
| FR-FILE-003 | User chỉ được tải/xem object qua signed URL có TTL ngắn và đúng ownership. | Must | URL không public; hết hạn đúng cấu hình; object key không do client tự chọn tùy ý. |
| FR-CV-001 | Người dùng phải tạo CV scan từ file đã upload bằng tác vụ bất đồng bộ. | Must | API trả 202, scan ID và status URL; retry cùng idempotency key không tạo scan trùng. |
| FR-CV-002 | AI phải trích xuất CV thành JSON theo schema versioned. | Must | Output validate được; field không chắc chắn có confidence/warning; raw model output không trở thành canonical CV. |
| FR-CV-003 | Kết quả scan phải được lưu ở trạng thái draft để người dùng xem và chỉnh sửa. | Must | UI/API đọc được draft; sửa draft dùng optimistic concurrency; canonical CV chưa đổi khi draft chưa confirm. |
| FR-CV-004 | Người dùng phải xác nhận draft trước khi tạo CV version chính thức. | Must | Confirm tạo immutable version mới, ghi actor/time/source scan; request lặp lại không tạo duplicate version. |
| FR-CV-005 | Hệ thống phải giữ lịch sử version và cho phép chọn version active. | Must | Mỗi version có schema version và checksum; version cũ không bị sửa; active version thuộc đúng CV/user. |
| FR-CV-006 | Người dùng phải sửa canonical data bằng cách tạo draft/version mới, không mutate version đã xác nhận. | Must | Update tạo version lineage; audit phân biệt AI extraction và user edit. |
| FR-CV-007 | Hệ thống phải phân tích CV về completeness, clarity, evidence, skill gap và action items. | Must | Analysis liên kết đúng CV version, prompt/model version; có structured findings và disclaimer. |
| FR-CV-008 | User phải xem lỗi scan và retry sau khi sửa nguyên nhân. | Must | Failure code không lộ dữ liệu/provider secret; retry tạo attempt có truy vết và không ghi đè audit cũ. |
| FR-CV-009 | User có thể archive hoặc xóa CV theo policy. | Must | CV không còn được dùng cho run mới; object/derived data đi qua retention/deletion workflow. |

## 5. AI interview

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-INT-001 | User phải tạo interview plan từ CV version, mục tiêu nghề nghiệp và tùy chọn job posting. | Must | Plan dùng snapshot input; CV/job bị xóa sau đó không làm mất provenance cần thiết của report. |
| FR-INT-002 | API phải cấp realtime session token ngắn hạn cho đúng interview và user. | Must | Token có TTL, scope, one-session binding; user khác không dùng được. |
| FR-INT-003 | Hệ thống phải hỗ trợ phỏng vấn giọng nói hai chiều qua Gemini Live. | Must | Audio/event được relay theo protocol; reconnect trong cửa sổ cho phép; session state transition hợp lệ. |
| FR-INT-004 | Hệ thống phải lưu transcript/event theo thứ tự, speaker và timestamp. | Must | Event có sequence duy nhất trong session; duplicate/reordered provider event được xử lý idempotent. |
| FR-INT-005 | User phải kết thúc hoặc hủy interview; timeout phải tự đóng session. | Must | State machine không cho kết thúc hai lần; worker evaluation chỉ chạy cho session đủ điều kiện. |
| FR-INT-006 | Sau interview, OpenAI phải tạo evaluation có cấu trúc dựa trên transcript và rubric version. | Must | Report có score theo dimension, evidence reference, strengths, gaps và action items; model/prompt/rubric được lưu. |
| FR-INT-007 | User phải xem report và trạng thái xử lý bất đồng bộ. | Must | API trả processing/ready/failed; report chỉ thuộc owner; lỗi evaluation có thể retry an toàn. |
| FR-INT-008 | User có thể báo cáo transcript/evaluation không chính xác. | Should | Feedback liên kết session/report version; không sửa audit artifact; được đưa vào quality review. |

## 6. Job discovery, search và application tracking

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-JOB-001 | Hệ thống phải ingest job từ các nguồn được phép vào chỉ mục nội bộ. | Must | Mỗi record có source, source job ID/URL, first_seen, last_seen, verification status và raw snapshot reference. |
| FR-JOB-002 | User phải tìm job realtime trên web khi chỉ mục nội bộ không đủ mới hoặc đủ rộng. | Must | Search run lưu query, provider, thời điểm và result provenance; provider result không được mặc định coi là active. |
| FR-JOB-003 | Hệ thống phải xác minh source URL và tín hiệu còn hiệu lực trước khi gắn nhãn verified. | Must | Có checked_at, HTTP/outcome và expiry policy; job hỏng/hết hạn bị hạ hạng hoặc loại. |
| FR-JOB-004 | Job từ nhiều nguồn phải được normalize và deduplicate. | Must | Canonical identity dùng source ID khi có và fingerprint khi không có; merge không làm mất provenance/snapshot. |
| FR-JOB-005 | Job detail phải hiển thị normalized JD, source URL, source name và freshness. | Must | Nếu không lấy được JD đầy đủ phải đánh dấu partial; không tự dựng điều kiện tuyển dụng không có nguồn. |
| FR-JOB-006 | Search nội bộ phải kết hợp PostgreSQL FTS, filter có cấu trúc và pgvector semantic retrieval. | Must | Query hỗ trợ role/location/remote/type/salary/skills; top-K có score component để debug offline. |
| FR-JOB-007 | Hệ thống phải rerank candidate top-K theo CV, preference, interview signals và job freshness. | Must | Ranking versioned; hard filter chạy trước explanation; cùng snapshot/config cho kết quả tái lập trong tolerance. |
| FR-JOB-008 | Chỉ một số kết quả đầu mới dùng LLM để tạo giải thích. | Must | Explanation không thay đổi rank; nêu evidence từ candidate/job; không bịa salary/skill; có model run/cost. |
| FR-JOB-009 | Search run dài phải stream progress/result qua SSE và có endpoint lấy trạng thái. | Must | Reconnect bằng event ID hoặc polling; kết quả cuối lưu được; disconnect client không hủy run ngoài ý muốn. |
| FR-JOB-010 | User phải save, dismiss và ghi nhận viewed/applied cho job. | Must | Interaction idempotent theo user/job/type; applied có status history và optional note/link. |
| FR-JOB-011 | Hệ thống phải tự làm stale/expire job theo nguồn và lần xác minh cuối. | Must | Job quá freshness window không được gắn verified; scheduler có metric và audit outcome. |
| FR-JOB-012 | User phải báo job sai, hết hạn hoặc đáng ngờ. | Should | Report được deduplicate, chuyển moderation queue và có ảnh hưởng verification theo policy. |

## 7. Candidate profile và recommendation

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-REC-001 | Hệ thống phải tạo candidate discovery profile từ CV active, preference và interview summaries. | Must | Profile có input version IDs và generated timestamp; thay đổi input đánh dấu profile stale. |
| FR-REC-002 | User phải yêu cầu recommendation run và lấy danh sách đã xếp hạng. | Must | Run lưu candidate/job snapshot, ranking version và score breakdown; retry idempotent. |
| FR-REC-003 | Recommendation phải giải thích skill match, gap, location/work-mode fit và freshness. | Must | Explanation trích evidence; gap không được trình bày như sự thật tuyệt đối khi source thiếu. |
| FR-REC-004 | Feedback của user phải được ghi nhận để đánh giá retrieval/ranking. | Should | Feedback không trực tiếp train model nếu thiếu consent; có event taxonomy và experiment attribution. |

## 8. Subscription, credit và usage

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-BILL-001 | User phải xem plan catalog và entitlement hiện tại. | Must | Price/currency/credit allowance có effective version; client không tự quyết định entitlement. |
| FR-BILL-002 | Hệ thống phải tạo checkout/portal session qua payment adapter. | Must | Redirect URL allowlisted; request idempotent; không lưu card data. |
| FR-BILL-003 | Webhook payment phải được xác minh chữ ký và xử lý idempotent. | Must | Event inbox unique theo provider/event ID; duplicate không tạo subscription/credit hai lần; raw payload có retention. |
| FR-BILL-004 | Credit balance phải dựa trên append-only ledger. | Must | Balance khớp tổng ledger; adjustment có actor/reason; không update/xóa ledger entry đã posted. |
| FR-BILL-005 | Tác vụ tốn credit phải reserve trước và settle/refund sau. | Must | Concurrent request không overspend; timeout có reconciliation; provider failure không mất credit sai. |
| FR-BILL-006 | User phải xem lịch sử credit và usage dễ hiểu. | Must | Mỗi entry có action, amount, occurred_at và reference; dữ liệu nội bộ nhạy cảm không lộ. |

| FR-BILL-007 | Hệ thống phải hỗ trợ catalog versioned gồm monthly subscription và one-time top-up offers. | Must | Catalog active trả đúng offer, VND amount, interval và credit grant; checkout lưu snapshot/version; version đã publish không bị sửa. |
| FR-BILL-008 | Successful subscription payment phải cấp credit đúng một lần cho từng billing period và credit hết hạn cuối kỳ. | Must | Duplicate webhook không cấp lại; cancel giữ quyền đến hết kỳ; payment failed không grant; không rollover. |
| FR-BILL-009 | Verified user phải nhận signup trial một lần theo policy active. | Must | Email verification cấp 50 credits có hạn 7 ngày; retry/login/link identity không cấp lần hai; expiry không giảm paid credits. |
| FR-BILL-010 | Credit phải được giữ trong bucket theo nguồn và consume theo thứ tự trial, subscription, top-up. | Must | Earliest expiry được dùng trước; concurrent reservation không overspend; release trả về đúng bucket/expiry; balance API trả breakdown. |
| FR-BILL-011 | Payment refund/chargeback và feature refund phải có ledger/review workflow. | Must | Unspent grant được reversal idempotent; credit đã dùng chuyển account review/debt; không sửa ledger cũ hoặc tạo balance âm âm thầm. |

## 9. Privacy, administration và operations

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---:|---|
| FR-PRIV-001 | User phải yêu cầu export dữ liệu cá nhân. | Must | Tác vụ async, artifact mã hóa/signed URL TTL, audit đầy đủ và hết hạn theo policy. |
| FR-PRIV-002 | User phải yêu cầu xóa tài khoản/dữ liệu theo retention và nghĩa vụ pháp lý. | Must | Workflow bao phủ DB, object, cache và derived data; trạng thái/ngoại lệ retention được công bố; access bị revoke. |
| FR-PRIV-003 | User phải xem và rút consent có thể rút. | Must | Withdrawal có hiệu lực cho xử lý tương lai; lịch sử consent không bị xóa khỏi audit bắt buộc. |
| FR-ADMIN-001 | Admin được phép tìm user/resource theo identifier tối thiểu cần thiết. | Must | Chỉ role/scope phù hợp; query và view được audit; PII masking theo role. |
| FR-ADMIN-002 | Admin phải quản lý prompt, rubric và model configuration qua version bất biến. | Must | Version publish có actor/time; run tham chiếu version cụ thể; rollback bằng activate version cũ. |
| FR-ADMIN-003 | Admin phải xem và retry background job theo policy. | Must | Retry idempotent, có reason/audit; payload nhạy cảm được redact. |
| FR-ADMIN-004 | Admin phải xem job source health, stale rate và moderation report. | Must | Có filter/source/time range; action disable source hoặc invalidate posting được audit. |
| FR-ADMIN-005 | Admin phải quản lý plan/credit adjustment với dual-control policy cho thao tác rủi ro. | Should | Adjustment có reason/reference; giới hạn scope; action giá trị lớn yêu cầu approval nếu policy bật. |
| FR-OPS-001 | Hệ thống phải cung cấp liveness, readiness và dependency diagnostics có kiểm soát. | Must | Public health không lộ secret; readiness fail khi instance không nên nhận traffic; dependency detail giới hạn cho ops. |
| FR-OPS-002 | Mọi request/run/job phải có correlation ID xuyên suốt API, queue và provider. | Must | Có thể truy từ request đến model run và side effect; ID xuất hiện trong structured log/trace. |
| FR-OPS-003 | Hệ thống phải phát hiện và hạn chế abuse bằng distributed rate limit/quota. | Must | Limit nhất quán giữa instance; key theo user/IP/action; response có retry metadata và không dựa vào memory một process. |

## 10. Ngoài phạm vi Product v1

- Marketplace cho nhà tuyển dụng đăng tin trực tiếp.
- Applicant Tracking System đầy đủ cho doanh nghiệp.
- Quyết định tuyển dụng tự động hoặc loại ứng viên tự động.
- Mạng xã hội nghề nghiệp.
- Mobile native application.
- Training foundation model bằng dữ liệu người dùng.
- Cam kết mọi website việc làm đều có thể crawl/search; nguồn phải tuân thủ điều khoản và quyền truy cập.

## 11. Traceability

- API operation liên kết requirement qua <code>x-requirement-ids</code>.
- Logical tables trong database schema nêu domain requirement tương ứng.
- Architecture flow dùng cùng resource/state name với OpenAPI.
- Test case nên có requirement ID trong tên, marker hoặc metadata.
