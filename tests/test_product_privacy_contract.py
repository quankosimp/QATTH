from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_privacy_contract_exposes_required_routes() -> None:
    source = (ROOT / "backend/app/api/v1/privacy.py").read_text()
    assert '"/privacy/exports"' in source
    assert '"/privacy/deletions"' in source
    assert '"/privacy/requests/{request_id}"' in source
    assert 'alias="Idempotency-Key"' in source


def test_privacy_workflow_has_mandatory_checkpoints() -> None:
    source = (ROOT / "backend/app/services/product_privacy.py").read_text()
    for checkpoint in ("access_revoked", "objects_deleted", "domain_data_purged", "cache_purged", "retention_recorded"):
        assert checkpoint in source
    assert "AESGCM" in source
    assert "retention_exceptions" in source
    assert "DeletionTombstone" in source
