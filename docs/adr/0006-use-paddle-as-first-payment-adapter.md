# ADR 0006: Use Paddle as the first production payment adapter

- Status: Accepted
- Date: 2026-07-15

## Context

The billing specification requires recurring monthly subscriptions, one-time top-ups, a hosted customer portal, VND prices, signed webhooks and a provider-neutral public contract. SePay covers local bank collection well but does not provide the complete recurring subscription and customer portal lifecycle required by Product v1.

## Decision

Paddle Billing is the first production adapter. The billing domain remains provider-neutral:

- Public checkout uses the internal offer ID.
- `PAYMENT_PADDLE_PRICE_IDS` maps internal offer codes to Paddle price IDs inside the adapter only.
- Paddle transaction, customer and subscription IDs are stored only as provider references.
- Webhooks are verified from the unmodified raw body using `Paddle-Signature`, HMAC-SHA256 and a five-second replay window.
- `transaction.completed`, approved refund/chargeback adjustments and `subscription.canceled` are normalized before the domain processes them.
- Checkout and portal URLs must be HTTPS provider URLs; QATTH never handles card or bank credentials.
- Mock payment remains available only in local, development and test environments.

## Operational requirements

- Pin Paddle API version `1`.
- Use `https://sandbox-api.paddle.com` outside live production and `https://api.paddle.com` for live traffic.
- Configure one Paddle price for every active internal offer code.
- Configure webhook delivery for `transaction.completed`, `adjustment.created`, `adjustment.updated` and `subscription.canceled`.
- Treat webhooks as authoritative for grants. A browser redirect never grants credits.
- Reconcile provider transactions, subscriptions and failed inbox events on a scheduled job.

## Consequences

Paddle supplies the required subscription and portal lifecycle without coupling public APIs to provider price IDs. The adapter adds an external configuration mapping and a provider approval dependency. Paddle does not support arbitrary client-supplied idempotency keys, so unknown checkout-create outcomes require reconciliation rather than blind retries.

## References

- [Create a Paddle transaction](https://developer.paddle.com/api-reference/transactions/create-transaction)
- [Create a customer portal session](https://developer.paddle.com/api-reference/customer-portals/create-customer-portal-session)
- [Verify Paddle webhook signatures](https://developer.paddle.com/webhooks/about/signature-verification)
