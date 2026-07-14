#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.main import app  # noqa: E402


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
PARTIAL_OPERATIONS = set()
NEW_OPERATION_METADATA = {
    ("/v1/admin/credit-adjustments/{adjustment_id}", "get"): ("getCreditAdjustment", ["FR-ADMIN-005", "FR-BILL-004"], ["admin:billing:read"]),
    ("/v1/admin/credit-adjustments/{adjustment_id}/approve", "post"): ("approveCreditAdjustment", ["FR-ADMIN-005", "FR-BILL-004"], ["admin:billing:approve"]),
    ("/v1/admin/credit-adjustments/{adjustment_id}/reject", "post"): ("rejectCreditAdjustment", ["FR-ADMIN-005", "FR-BILL-004"], ["admin:billing:approve"]),
    ("/v1/admin/job-sources/{source_id}", "patch"): ("updateJobSource", ["FR-ADMIN-004"], ["admin:jobs:write"]),
    ("/v1/admin/model-configurations/{configuration_id}/activate", "post"): ("activateModelConfiguration", ["FR-ADMIN-002", "NFR-AI-006"], ["admin:model:write"]),
    ("/v1/admin/model-configurations/{configuration_id}/evaluation-reports", "get"): ("listModelEvaluationReports", ["FR-ADMIN-002", "NFR-AI-002", "NFR-AI-003", "NFR-AI-006"], ["admin:model:read"]),
    ("/v1/admin/model-configurations/{configuration_id}/evaluation-reports", "post"): ("createModelEvaluationReport", ["FR-ADMIN-002", "NFR-AI-002", "NFR-AI-003", "NFR-AI-006"], ["admin:model:write"]),
    ("/v1/admin/moderation-cases", "get"): ("listModerationCases", ["FR-ADMIN-004"], ["admin:jobs:read"]),
    ("/v1/admin/moderation-cases/{case_id}/resolve", "post"): ("resolveModerationCase", ["FR-ADMIN-004"], ["admin:jobs:write"]),
    ("/v1/admin/resources/{resource_type}/{resource_id}", "get"): ("getAdminResource", ["FR-ADMIN-001"], ["admin:resources:read"]),
    ("/v1/admin/users", "get"): ("searchAdminUsers", ["FR-ADMIN-001"], ["admin:users:read"]),
    ("/v1/admin/users/{user_id}/status", "patch"): ("updateAdminUserStatus", ["FR-AUTH-004", "FR-ADMIN-001"], ["admin:users:write"]),
    ("/v1/cv-analyses/{analysis_id}/retry", "post"): ("retryCvAnalysis", ["FR-CV-008"], []),
    ("/v1/cv-scans/{scan_id}/retry", "post"): ("retryCvScan", ["FR-CV-008"], []),
    ("/v1/cv-versions/{version_id}/drafts", "post"): ("createCvVersionDraft", ["FR-CV-005", "FR-CV-006"], []),
    ("/v1/cvs/{cv_id}/archive", "post"): ("archiveCv", ["FR-CV-009"], []),
    ("/v1/interviews/{interview_id}/cancel", "post"): ("cancelInterview", ["FR-INT-002", "FR-INT-004"], []),
    ("/v1/interviews/{interview_id}/feedback", "post"): ("createInterviewFeedback", ["FR-INT-008", "NFR-AI-007"], []),
    ("/v1/interviews/{interview_id}/report/retry", "post"): ("retryInterviewReport", ["FR-INT-006", "NFR-AVL-003"], []),
    ("/v1/me/sessions", "get"): ("listSessions", ["FR-AUTH-003"], []),
    ("/v1/me/sessions/{session_id}", "delete"): ("revokeSession", ["FR-AUTH-003"], []),
    ("/v1/ops/diagnostics", "get"): ("getOpsDiagnostics", ["FR-OPS-001", "NFR-AVL-002"], ["ops:jobs:read"]),
    ("/v1/ops/provider-usage", "get"): ("getProviderUsage", ["FR-OPS-002", "NFR-OBS-002", "NFR-AI-005"], ["ops:jobs:read"]),
    ("/v1/recommendation-runs/{run_id}/feedback", "post"): ("createRecommendationFeedback", ["FR-REC-004", "NFR-AI-007"], []),
}
PRESERVED_OPERATION_FIELDS = (
    "summary",
    "description",
    "operationId",
    "tags",
    "security",
    "x-requirement-ids",
)


def synchronize(manual: dict, runtime: dict) -> dict:
    result = copy.deepcopy(manual)
    description = str(result.get("info", {}).get("description") or "")
    result["info"]["description"] = description.replace(
        "implemented-demo, partial, or planned",
        "implemented, partial, or planned",
    )
    result["info"]["x-contract-source"] = "FastAPI runtime schema plus product requirement metadata"

    result.setdefault("components", {}).setdefault("schemas", {}).update(
        copy.deepcopy(runtime.get("components", {}).get("schemas", {}))
    )
    result["components"].setdefault("securitySchemes", {}).update(
        copy.deepcopy(runtime.get("components", {}).get("securitySchemes", {}))
    )

    runtime_operations = {
        (path, method)
        for path, path_item in runtime["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    for path, method in sorted(runtime_operations):
        runtime_operation = copy.deepcopy(runtime["paths"][path][method])
        old_operation = result.get("paths", {}).get(path, {}).get(method, {})
        for field in PRESERVED_OPERATION_FIELDS:
            if field in old_operation:
                runtime_operation[field] = copy.deepcopy(old_operation[field])
        if "default" in old_operation.get("responses", {}):
            runtime_operation.setdefault("responses", {})["default"] = copy.deepcopy(old_operation["responses"]["default"])

        metadata = NEW_OPERATION_METADATA.get((path, method))
        if metadata:
            operation_id, requirement_ids, scopes = metadata
            runtime_operation["operationId"] = operation_id
            runtime_operation["x-requirement-ids"] = requirement_ids
            if scopes:
                runtime_operation["x-required-scopes"] = scopes
        if not runtime_operation.get("x-requirement-ids"):
            raise RuntimeError(f"Missing requirement mapping for {method.upper()} {path}")
        runtime_operation["x-implementation-status"] = (
            "partial" if (path, method) in PARTIAL_OPERATIONS else "implemented"
        )
        result.setdefault("paths", {}).setdefault(path, {})[method] = runtime_operation

    websocket = result.get("paths", {}).get("/v1/interviews/{interview_id}/realtime", {}).get("get")
    if websocket:
        websocket["x-implementation-status"] = "partial"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the committed OpenAPI contract with FastAPI runtime routes.")
    parser.add_argument("--check", action="store_true", help="Fail when the committed contract is not synchronized.")
    args = parser.parse_args()
    path = ROOT / "docs/api/openapi.yaml"
    manual = yaml.safe_load(path.read_text(encoding="utf-8"))
    synchronized = synchronize(manual, app.openapi())
    rendered = yaml.safe_dump(synchronized, sort_keys=False, allow_unicode=True, width=120)
    if args.check:
        if yaml.safe_load(path.read_text(encoding="utf-8")) != yaml.safe_load(rendered):
            print("docs/api/openapi.yaml is not synchronized", file=sys.stderr)
            return 1
        return 0
    path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
