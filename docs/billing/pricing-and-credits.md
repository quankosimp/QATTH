# Pricing and Credits Specification

- Status: Product v1 draft
- Catalog version: <code>2026-07-14-product-v1-draft</code>
- Currency: VND
- Owners: Product, Backend, Finance operations
- Related requirements: FR-BILL-001 through FR-BILL-011

## 1. Purpose

Tài liệu này là nguồn chuẩn cho pricing, subscription, top-up, signup trial và credit accounting của QATTH Product v1.

Spec kế thừa các nguyên tắc đã được kiểm chứng trong QATTH v1:

- Credit ledger append-only.
- Mutation idempotent.
- Trial balance tách khỏi paid balance.
- Trial được dùng trước paid credits.
- Trial expiry không làm giảm paid balance.
- Pricing có thể thay đổi lúc runtime.
- Worker/payment retry không được grant hoặc consume hai lần.
- Enqueue/provider failure phải có compensation hoặc recovery.

Product v1 mở rộng mô hình cũ thành hybrid subscription + top-up, đồng thời giữ billing core độc lập payment provider.

## 2. Product positioning

QATTH hướng tới sinh viên Việt Nam nên giá subscription baseline thấp hơn các sản phẩm CV/interview AI quốc tế. Kickresume công bố gói tháng khoảng 24 USD và Huru khoảng 24,99 EUR/tháng; các mức này chỉ dùng để tham khảo positioning, không dùng để quy đổi trực tiếp.

References:

- [Kickresume pricing](https://www.kickresume.com/en/pricing/sale/)
- [Huru pricing](https://huru.ai/es/)
- [Final Round AI pricing overview](https://www.finalroundai.com/blog/what-is-final-round-ai)

Tất cả giá dưới đây là consumer-facing gross baseline. Product/finance phải hoàn tất tax và legal review trước khi activate production catalog.

## 3. Terminology

| Term | Meaning |
|---|---|
| Credit | Đơn vị sử dụng nội bộ, không phải tiền và không quy đổi ra tiền |
| Offer | Sản phẩm thương mại có thể checkout: subscription hoặc top-up |
| Catalog version | Snapshot bất biến của offers và feature prices |
| Credit grant | Quyền credit được tạo bởi trial, subscription, top-up hoặc adjustment |
| Credit bucket | Phần credit có cùng nguồn và expiry |
| Available | Credit đã grant, chưa consume/expire và chưa reserve |
| Reserved | Credit được giữ cho một action đang xử lý |
| Settled | Reservation đã trở thành charge |
| Released | Reservation được trả lại đúng bucket do action không billable |
| Ledger | Lịch sử append-only của grant, charge, expire, refund và adjustment |

## 4. Active baseline catalog

### 4.1 Monthly subscriptions

| Offer code | Display name | Amount | Billing interval | Credit grant |
|---|---|---:|---|---:|
| STARTER_MONTHLY | Starter | 49.000 VND | Month | 60 |
| PRO_MONTHLY | Pro | 99.000 VND | Month | 150 |
| PREMIUM_MONTHLY | Premium | 199.000 VND | Month | 350 |

Rules:

- Subscription tự gia hạn đến khi cancel.
- Credit được grant sau verified successful payment event của từng billing period.
- Mỗi subscription và billing period chỉ có tối đa một grant.
- Subscription credits hết hạn tại <code>current_period_end</code>.
- Không rollover sang kỳ tiếp theo.
- Cancel không thu hồi quyền đã trả tiền; entitlement và credit còn hiệu lực đến hết kỳ.
- Payment failed hoặc past due không tạo grant mới.
- Product v1 không hard-gate core features theo tier; tier khác nhau chủ yếu ở recurring credit grant.
- Provider customer/subscription/price identifiers là mapping của adapter, không phải public offer identity.

### 4.2 One-time top-ups inherited from QATTH v1

| Offer code | Display name | Amount | Credit grant |
|---|---|---:|---:|
| TOPUP_STARTER | Starter top-up | 70.000 VND | 70 |
| TOPUP_PRO | Pro top-up | 100.000 VND | 105 |
| TOPUP_PREMIUM | Premium top-up | 200.000 VND | 220 |
| TOPUP_MAX | Max top-up | 300.000 VND | 335 |

Rules:

- Top-up checkout là giao dịch một lần.
- Top-up grant chỉ được post sau verified successful payment event.
- Top-up credits mặc định không hết hạn.
- Duplicate provider event hoặc checkout retry không tạo grant thứ hai.
- Offer cũ có thể ngừng bán nhưng transaction và ledger lịch sử vẫn tham chiếu được version cũ.

### 4.3 Feature credit pricing inherited from QATTH v1

| Feature key | Credit cost | Product v1 rule |
|---|---:|---|
| cv_upload | 0 | Upload, scan structured JSON, edit và confirm CV không thu credit |
| cv_analysis | 10 | Reserve khi bắt đầu analysis, settle khi result hoàn thành |
| search_run | 0 | Indexed/live job search miễn phí, kiểm soát bằng quota và rate limit |
| interview_session | 25 | Một session tối đa 30 phút |

Feature price bằng zero vẫn là cấu hình hợp lệ và phải xuất hiện trong catalog. Zero-cost action không tạo credit reservation nhưng vẫn ghi usage/model cost để chống abuse và đánh giá unit economics.

### 4.4 Signup trial

| Field | Value |
|---|---|
| Policy key | SIGNUP_VERIFIED_EMAIL |
| Enabled | true |
| Trigger | Email/OIDC email verification completed |
| Credit grant | 50 |
| Validity | 7 days |
| Grants per user | 1 |

Rules:

- Trial grant idempotent và chỉ chạy sau verified-email transition.
- Login lặp lại hoặc liên kết thêm identity không cấp lại trial.
- Trial bucket tách khỏi subscription/top-up.
- Trial expiry post ledger entry cho phần còn lại và không ảnh hưởng paid buckets.
- User bị khóa hoặc pending deletion không nhận trial mới.
- Admin có thể disable policy bằng version mới nhưng không sửa grant đã tồn tại.

## 5. Credit bucket and spend rules

### 5.1 Bucket types

| Bucket type | Source | Expiry |
|---|---|---|
| trial | Signup trial policy | Seven days after grant |
| subscription | Successful recurring period payment | Current period end |
| topup | Successful one-time payment | No expiry by default |
| adjustment | Audited admin/system action | Explicit per adjustment |

### 5.2 Spend order

Credit allocation luôn theo thứ tự:

1. Trial bucket có expiry gần nhất.
2. Subscription bucket có expiry gần nhất.
3. Top-up bucket cũ nhất.
4. Adjustment bucket theo expiry/source policy.

Trong cùng bucket type, dùng earliest-expiry-first; bucket không expiry dùng oldest-grant-first.

Balance response phải tách:

- Total available.
- Total reserved.
- Trial available và nearest expiry.
- Subscription available và từng period expiry.
- Top-up available.
- Adjustment available nếu có.

### 5.3 No negative balance

- Available balance không được âm.
- Hai request đồng thời không được reserve cùng một credit.
- Không fallback sang Redis hoặc memory khi PostgreSQL transaction thất bại.
- Payment refund/chargeback có thể tạo account debt/review state, nhưng không âm thầm biến user balance thành số âm.
- Account ở review/locked không được tạo paid action mới.

## 6. Reservation lifecycle

~~~mermaid
stateDiagram-v2
    [*] --> reserved
    reserved --> settled: billable success
    reserved --> released: not billable / terminal failure
    reserved --> expired: reconciliation timeout
    expired --> released: no provider side effect
    expired --> settled: provider side effect confirmed
~~~

### 6.1 Reserve

Trong một PostgreSQL transaction:

1. Resolve active feature price và catalog/config version.
2. Validate entitlement, quota, account state và action duration.
3. Lock relevant credit account/bucket rows.
4. Settle expired buckets.
5. Allocate theo spend order.
6. Tạo reservation và reservation allocations.
7. Persist business resource/outbox event.
8. Commit.

Cùng <code>Idempotency-Key</code> và request hash trả lại reservation/resource cũ. Cùng key khác request hash trả conflict.

### 6.2 Settle

- CV analysis settle 10 credits khi structured result được persist thành công.
- Interview reserve 25 credits trước khi mở Gemini Live.
- Interview trở thành billable khi session vào trạng thái live và gửi thành công meaningful AI interview content đầu tiên.
- Failure trước <code>billable_started_at</code> release toàn bộ reservation.
- Failure sau <code>billable_started_at</code> settle 25 credits; admin có thể tạo goodwill refund bằng audited adjustment.
- Search có cost zero nên không reserve nhưng vẫn persist search/model usage.
- Settle post ledger charge theo từng bucket allocation và đánh dấu reservation settled trong cùng transaction.

### 6.3 Release and reconciliation

- Validation failure trước provider call không tạo reservation.
- Queue enqueue failure sau commit được outbox publisher retry; không release chỉ vì một lần publish thất bại.
- Terminal worker/provider failure trước billable point release đúng allocation gốc.
- Reservation quá hạn được reconciliation worker kiểm tra business/provider outcome trước settle hoặc release.
- Retry không tạo ledger row mới nhờ unique business reference và idempotency key.
- Release giữ nguyên expiry gốc; bucket đã hết hạn trong lúc action chạy được release rồi settle expiry trong cùng reconciliation transaction.

## 7. Ledger rules

Ledger entry types:

| Type | Signed amount | Meaning |
|---|---:|---|
| GRANT | Positive | Trial, subscription, top-up hoặc approved adjustment |
| CHARGE | Negative | Settled feature usage |
| RELEASE | 0 or audit-only | Reservation released; không làm đổi posted balance |
| EXPIRE | Negative | Unused expiring grant removed |
| REFUND | Positive | Restores a previously settled charge |
| REVERSAL | Negative | Reverses an unspent payment grant |
| ADJUSTMENT | Positive/negative | Audited manual correction |

Rules:

- Ledger append-only; không update/delete posted entry.
- Mỗi entry có user/account, bucket, type, amount, balance snapshot, business reference, idempotency key, actor/source và timestamp.
- Refund của feature usage trả về source bucket nếu còn hiệu lực; nếu source đã hết hạn, tạo adjustment bucket có expiry policy được ghi rõ.
- Admin adjustment bắt buộc actor, reason và external/internal reference.
- Credit không chuyển giữa users và không cash out.

## 8. Payment lifecycle

### 8.1 Checkout

- Client gửi <code>offer_id</code>, success URL và cancel URL.
- Server resolve active catalog; không nhận amount hoặc credit grant từ client.
- Checkout session idempotent.
- Redirect URL phải nằm trong allowlist.
- Payment adapter map internal offer sang provider price/product.
- Card/bank credential không đi qua hoặc được lưu bởi QATTH.

### 8.2 Webhook

1. Đọc raw body.
2. Xác minh provider signature và replay window.
3. Insert webhook inbox unique theo provider/event ID.
4. Normalize thành internal payment event.
5. Transaction cập nhật order/subscription projection và credit grant.
6. Mark processed hoặc retryable failure.
7. Reconciliation so sánh provider state định kỳ.

Webhook duplicate phải trả acknowledgement an toàn nhưng không lặp business effect.

### 8.3 Payment refund and chargeback

- Unspent credits từ payment grant được reverse bằng ledger, không sửa grant cũ.
- Nếu đã dùng một phần, reverse phần còn lại và chuyển account sang review/debt cho phần đã dùng.
- Account review không được tạo action tốn credit cho đến khi resolved.
- Refund/chargeback event idempotent và có audit.
- Goodwill feature refund độc lập payment refund.

## 9. Catalog versioning and administration

- Catalog version bất biến sau khi published.
- Draft version có thể chỉnh trước publish.
- Chỉ một version active tại một thời điểm cho cùng market/currency.
- Activation có effective timestamp, actor và reason.
- Checkout lưu offer/catalog snapshot đã dùng.
- Subscription renewal dùng offer version được subscription tham chiếu cho đến khi có explicit migration.
- Feature price thay đổi không ảnh hưởng reservation đã tạo.
- Database là source of truth; Redis/process cache chỉ là projection có TTL/invalidation.
- Cache refresh failure giữ last-known-good nhưng phát metric/log; operation tài chính có thể đọc authoritative DB khi version không chắc chắn.
- Admin không sửa ledger hoặc payment payload.
- Mọi activate, disable, adjustment và migration subscription đều audit.

## 10. Provider-neutral boundary

Core billing chỉ dùng internal concepts:

- Offer.
- Checkout session.
- Payment event.
- Subscription.
- Credit grant.
- Reservation.
- Ledger entry.

SePay, Paddle, Stripe hoặc provider khác chỉ tồn tại trong adapter mapping và metadata. Public API không trả provider-specific plan code làm canonical ID.

Paddle là production adapter đầu tiên theo [ADR 0006](../adr/0006-use-paddle-as-first-payment-adapter.md). Paddle price IDs được map từ internal offer code bằng cấu hình adapter, không được trả qua catalog API. Webhook production dùng header <code>Paddle-Signature</code>; <code>X-Payment-Signature</code> chỉ thuộc mock adapter local/test.

## 11. API contract summary

| Operation | Purpose |
|---|---|
| GET /v1/billing/catalog | Active subscriptions, top-ups và catalog version |
| GET /v1/billing/feature-pricing | Effective feature credit costs |
| GET /v1/billing/signup-trial-policy | Public-safe active trial policy |
| GET /v1/billing/subscription | Current subscription và period |
| GET /v1/billing/credits | Bucket breakdown và ledger page |
| POST /v1/billing/checkout-sessions | Checkout từ internal offer |
| POST /v1/billing/portal-sessions | Provider-neutral customer portal |
| POST /v1/webhooks/payments/{provider} | Verified raw webhook ingest |
| POST /v1/admin/billing/catalog-versions | Create draft catalog version |
| POST /v1/admin/billing/catalog-versions/{id}/activate | Activate catalog version |
| PUT /v1/admin/billing/feature-pricing/{key} | Publish feature price configuration |
| PUT /v1/admin/billing/signup-trial-policy | Publish trial policy |

## 12. Observability

Metrics tối thiểu:

- Checkout created/completed/failed theo offer type, không label user.
- Webhook received/duplicate/invalid/processed/backlog.
- Credit grant/charge/release/expire/refund theo source/feature.
- Reservation age và reconciliation outcome.
- Trial grant/consume/expire.
- Subscription renewal grant success.
- Account review/debt count.
- Provider payment-to-credit latency.
- AI/provider cost và gross revenue/credit consumption ở aggregate.

Alert bắt buộc cho duplicate invariant violation, webhook backlog, stale reservation, reconciliation mismatch và payment success không có credit grant.

## 13. Traceability

| Requirement | API | Logical entities | Required tests |
|---|---|---|---|
| FR-BILL-001, FR-BILL-007 | Catalog and feature-pricing reads | catalog_versions, offers, prices | Active version and exact baseline catalog |
| FR-BILL-002 | Checkout, portal, subscription | checkout_sessions, subscriptions | Offer resolution, redirect allowlist, renewal |
| FR-BILL-003 | Payment webhook | webhook_inbox, payment_events | Signature, replay, duplicate |
| FR-BILL-004 | Credit balance and ledger | credit_accounts, credit_buckets, ledger_entries | Concurrent grant/charge and reconciliation |
| FR-BILL-005 | Internal paid actions | reservations, reservation_allocations | Reserve, settle, release, timeout |
| FR-BILL-006 | Credit history | ledger_entries | Cursor page and safe descriptions |
| FR-BILL-008 | Subscription period grants | subscriptions, credit_buckets | One grant per paid period, expiry |
| FR-BILL-009 | Signup trial policy | trial_policies, credit_buckets | Verified email, one grant, seven-day expiry |
| FR-BILL-010 | Spend order and expiry | credit_buckets, allocations | Trial then subscription then top-up |
| FR-BILL-011 | Refund and chargeback | payment_events, ledger_entries, account_reviews | Unspent reversal and spent-credit review |

## 14. Out of scope

- Annual subscription.
- Credit rollover.
- Credit transfer or gifting.
- Family/team shared balance.
- Cash withdrawal.
- Per-minute interview settlement.
- Employer billing.
- Coupons, affiliate commission và regional multi-currency.
