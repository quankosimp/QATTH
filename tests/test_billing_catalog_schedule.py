from datetime import datetime, timezone

import pytest

from app.core.errors import AppError
from app.models.product_billing import BillingCatalogVersion
from app.services.product_billing import ProductBillingService


def _catalog(key: str, starts: datetime, ends: datetime | None = None) -> BillingCatalogVersion:
    return BillingCatalogVersion(
        version_key=key,
        market="VN",
        currency="VND",
        status="active",
        effective_from=starts,
        effective_to=ends,
    )


def test_catalog_activation_inserts_between_predecessor_and_successor() -> None:
    current = _catalog("current", datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 8, 1, tzinfo=timezone.utc))
    future = _catalog("future", datetime(2026, 8, 1, tzinfo=timezone.utc))
    inserted = BillingCatalogVersion(version_key="inserted", market="VN", currency="VND", status="draft")
    effective = datetime(2026, 7, 15, tzinfo=timezone.utc)

    ProductBillingService._schedule_catalog_activation(inserted, [current, future], effective)

    assert current.effective_to == effective
    assert inserted.effective_to == future.effective_from
    assert future.effective_to is None


def test_catalog_activation_rejects_duplicate_effective_time() -> None:
    effective = datetime(2026, 8, 1, tzinfo=timezone.utc)
    existing = _catalog("existing", effective)
    candidate = BillingCatalogVersion(version_key="candidate", market="VN", currency="VND", status="draft")

    with pytest.raises(AppError) as raised:
        ProductBillingService._schedule_catalog_activation(candidate, [existing], effective)

    assert raised.value.code == "BILLING_CATALOG_EFFECTIVE_TIME_CONFLICT"
