# ADR 0003: Use Provider-neutral Hybrid Billing with an Append-only Credit Ledger

- Status: Accepted
- Date: 2026-07-14
- Decision owners: Product, Backend architecture, Finance operations
- Related requirements: FR-BILL-001 through FR-BILL-011

## Context

QATTH Product v1 cần thu phí cho AI workloads có cost khác nhau nhưng vẫn giữ job search dễ tiếp cận cho sinh viên.

QATTH v1 đã có:

- One-time credit packages.
- Paid credit balance và append-only ledger.
- Trial bucket/ledger riêng.
- Trial-first consumption.
- Verified-email trial grant.
- Runtime feature pricing.
- Idempotent grant/consume.
- SePay/Paddle-specific payment logic.
- Reconciliation và compensation cho enqueue failure.

Thiết kế cũ chứng minh các accounting invariant hữu ích nhưng gắn catalog/payment behavior với provider và dùng mutable runtime overrides trong từng process. Product mới cần thêm recurring subscription, reservation trước AI action và catalog history bất biến.

## Decision

Product v1 dùng hybrid billing:

- Monthly subscription cấp expiring credits mỗi paid period.
- One-time top-up cấp non-expiring credits.
- Signup trial cấp expiring credits một lần.
- Credit buckets tách theo source và expiry.
- Spend order trial, subscription rồi top-up.
- Mọi posted balance mutation qua append-only ledger.
- Paid actions reserve trước, settle hoặc release sau outcome.
- Catalog, feature price và trial policy được version hóa.
- Billing core độc lập provider; provider chỉ nằm trong adapter và webhook normalization.
- PostgreSQL là accounting source of truth; cache không quyết định balance.

Baseline pricing và feature costs được định nghĩa trong [Pricing and Credits Specification](../billing/pricing-and-credits.md).

## Why

- Hybrid model cho phép recurring revenue nhưng vẫn hỗ trợ sinh viên chỉ muốn mua một lần.
- Credit giúp giới hạn AI cost mà không tạo price SKU cho từng provider call.
- Bucket tách nguồn giải quyết expiry, refund và spend order rõ ràng.
- Reservation tránh consume-then-refund race khi queue/provider lỗi.
- Append-only ledger và idempotency cho phép audit/reconciliation.
- Provider-neutral offer ID tránh phải thay API/domain khi đổi payment provider.
- Versioned catalog giữ lịch sử giá đúng với transaction và subscription đã bán.

## Alternatives considered

### Copy QATTH v1 exactly

Không chọn vì v1 chủ yếu là top-up, provider coupling cao và consume-before-enqueue cần compensation phức tạp. Product mới vẫn lấy giá baseline, trial/ledger invariant và reconciliation pattern.

### Subscription only

Không chọn vì sinh viên có nhu cầu theo đợt và có thể không muốn recurring payment. Top-up giảm friction cho nhu cầu CV/interview ngắn hạn.

### Top-up only

Không chọn vì thiếu recurring revenue và không tạo cơ chế grant định kỳ cho người dùng thường xuyên.

### Provider-owned credits

Không chọn vì provider payment không hiểu AI usage, expiry order hoặc multi-provider cost. QATTH phải giữ entitlement/accounting projection riêng.

### Mutable balance without ledger

Không chọn vì không audit/reconcile được duplicate webhook, admin adjustment, refund và retry.

### Per-minute interview charging

Không chọn trong Product v1 vì khó giải thích, khó reserve và Gemini Live cost không tuyến tính đơn giản theo thời lượng/context. Dùng fixed 25 credits cho tối đa 30 phút và đo cost thực tế trước khi xem xét lại.

## Consequences

Positive:

- Pricing/payment provider có thể thay mà không phá frontend/domain.
- Trial, subscription và top-up accounting rõ.
- Retry, webhook duplicate và worker failure có invariant kiểm thử được.
- Revenue và AI usage có thể reconcile.
- Catalog thay đổi không rewrite lịch sử.

Negative:

- Nhiều bảng và transaction hơn mutable balance đơn giản.
- Reservation timeout và bucket allocation cần reconciliation worker.
- Refund khi credit đã dùng cần account review/debt workflow.
- Hybrid subscription + top-up tăng số scenario test.
- Finance/product phải quản trị catalog version và unit economics.

## Guardrails

- Client không gửi authoritative amount hoặc credit grant.
- Không update/delete posted ledger entry.
- Không để balance âm âm thầm.
- Không grant từ webhook chưa verify.
- Không dùng Redis/memory làm accounting source of truth.
- Không dùng provider price ID làm public offer ID.
- Mỗi payment period/event/action có unique idempotent business reference.
- Admin adjustment cần actor, reason và audit.
- Feature cost zero là hợp lệ.
- Model/provider cost vẫn được đo cho zero-credit action.

## Migration from QATTH v1

- Map four legacy packages sang four top-up offers.
- Preserve legacy transaction/provider references trong metadata.
- Import paid ledger bằng immutable migration entries và reconcile balance.
- Import active trial bucket với original expiry; không cấp trial lần hai.
- Không copy process-local pricing override làm source of truth.
- Không expose SePay-specific plan token trong Product v1 contract.
- Subscription catalog bắt đầu bằng version mới; legacy top-up không tự chuyển thành subscription.

## Revisit triggers

- Gemini/OpenAI unit cost làm fixed feature prices không còn an toàn.
- Người dùng yêu cầu rollover hoặc annual plan đủ lớn.
- Credit liability/refund regulation yêu cầu policy khác.
- Payment provider không hỗ trợ lifecycle cần thiết.
- Usage data chứng minh per-minute interview pricing dễ hiểu và công bằng hơn.
