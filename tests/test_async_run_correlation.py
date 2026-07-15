from dataclasses import dataclass

from app.models.product_jobs import JobSearchDispatch
from app.models.product_privacy import PrivacyDispatch
from app.models.product_recommendations import RecommendationDispatch
from app.services.product_job_search import ProductJobSearchService
from app.services.product_privacy import ProductPrivacyService
from app.services.product_recommendations import ProductRecommendationService
from app.workers.tasks import (
    execute_product_job_search_task,
    execute_product_privacy_request_task,
    execute_product_recommendation_task,
)


@dataclass
class ParentRun:
    correlation_id: str


class DispatchDB:
    def __init__(self, dispatch, parent) -> None:
        self.dispatch = dispatch
        self.parent = parent
        self.commits = 0

    def scalar(self, _query):
        return self.dispatch

    def get(self, _model, _resource_id):
        return self.parent

    def commit(self) -> None:
        self.commits += 1


def _capture(monkeypatch, task):
    calls: list[dict] = []

    def apply_async(*, args, headers):
        calls.append({"args": args, "headers": headers})

    monkeypatch.setattr(task, "apply_async", apply_async)
    return calls


def test_job_search_dispatch_propagates_originating_request_id(monkeypatch) -> None:
    dispatch = JobSearchDispatch(run_id="run-1", payload={"run_id": "run-1"}, status="pending", attempts=0)
    db = DispatchDB(dispatch, ParentRun("request-job-search"))
    service = object.__new__(ProductJobSearchService)
    service.db = db
    calls = _capture(monkeypatch, execute_product_job_search_task)

    assert service.publish_dispatch_for_run("run-1") is True
    assert calls == [{"args": ["run-1"], "headers": {"request_id": "request-job-search"}}]


def test_recommendation_dispatch_propagates_originating_request_id(monkeypatch) -> None:
    dispatch = RecommendationDispatch(run_id="run-2", payload={"run_id": "run-2"}, status="pending", attempts=0)
    db = DispatchDB(dispatch, ParentRun("request-recommendation"))
    service = object.__new__(ProductRecommendationService)
    service.db = db
    calls = _capture(monkeypatch, execute_product_recommendation_task)

    assert service.publish_dispatch_for_run("run-2") is True
    assert calls == [{"args": ["run-2"], "headers": {"request_id": "request-recommendation"}}]


def test_privacy_dispatch_propagates_originating_request_id(monkeypatch) -> None:
    dispatch = PrivacyDispatch(request_id="request-3", payload={"request_id": "request-3"}, status="pending", attempts=0)
    db = DispatchDB(dispatch, ParentRun("request-privacy"))
    service = object.__new__(ProductPrivacyService)
    service.db = db
    calls = _capture(monkeypatch, execute_product_privacy_request_task)

    assert service.publish_dispatch("request-3") is True
    assert calls == [{"args": ["request-3"], "headers": {"request_id": "request-privacy"}}]
