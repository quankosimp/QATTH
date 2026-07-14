from pathlib import Path

import yaml

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def test_committed_openapi_covers_every_runtime_operation() -> None:
    committed = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    runtime = app.openapi()
    runtime_operations = {
        (path, method)
        for path, path_item in runtime["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    committed_operations = {
        (path, method)
        for path, path_item in committed["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    assert runtime_operations <= committed_operations
    for path, method in runtime_operations:
        operation = committed["paths"][path][method]
        assert operation["x-implementation-status"] in {"implemented", "partial"}
        assert operation["x-requirement-ids"]


def test_websocket_contract_is_preserved_outside_fastapi_openapi() -> None:
    committed = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    operation = committed["paths"]["/v1/interviews/{interview_id}/realtime"]["get"]
    assert operation["x-implementation-status"] == "partial"
    assert "FR-INT-003" in operation["x-requirement-ids"]
