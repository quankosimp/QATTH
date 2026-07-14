import pytest

from app.core.errors import AppError
from app.services.product_billing import ProductBillingService


def test_partial_reversal_rounding_is_cumulative_and_bounded() -> None:
    amount = 0
    credits = 0
    increments = []
    for event_amount in (1, 1, 1):
        amount, next_credits, increment = ProductBillingService._cumulative_reversal(
            original_amount=3,
            granted_credits=100,
            reversed_amount=amount,
            reversed_credits=credits,
            event_amount=event_amount,
        )
        credits = next_credits
        increments.append(increment)

    assert increments == [34, 33, 33]
    assert credits == 100


def test_cumulative_reversal_rejects_amount_above_original_payment() -> None:
    with pytest.raises(AppError) as raised:
        ProductBillingService._cumulative_reversal(
            original_amount=100,
            granted_credits=70,
            reversed_amount=60,
            reversed_credits=42,
            event_amount=41,
        )
    assert raised.value.code == "PAYMENT_REVERSAL_AMOUNT_INVALID"
