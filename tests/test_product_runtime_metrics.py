from prometheus_client import CollectorRegistry

from app.core.product_metrics import ProductRuntimeCollector, register_product_metrics


def _families(collector: ProductRuntimeCollector):
    return {family.name: family for family in collector.collect()}


def test_runtime_collector_exposes_required_operational_dimensions() -> None:
    collector = ProductRuntimeCollector(
        lambda: {
            "queues": [("celery", 3, 12.0)],
            "dispatches": [("privacy", 2, 30.0)],
            "interviews": {"live": 4, "interrupted": 1},
            "jobs": {"active": 20, "stale": 5},
            "oldest_active_job_age": 90.0,
            "privacy_retention": (2, 45.0),
        }
    )

    families = _families(collector)

    assert {
        "qatth_runtime_metrics_scrape_success",
        "qatth_db_pool_connections",
        "qatth_queue_projected_depth",
        "qatth_queue_oldest_age_seconds",
        "qatth_dispatch_pending",
        "qatth_dispatch_oldest_age_seconds",
        "qatth_interview_active",
        "qatth_job_catalog",
        "qatth_job_oldest_active_age_seconds",
        "qatth_privacy_expired_artifacts",
        "qatth_privacy_expired_artifact_oldest_age_seconds",
    }.issubset(families)
    assert families["qatth_queue_projected_depth"].samples[0].value == 3
    assert families["qatth_interview_active"].samples[0].labels["status"] == "live"


def test_runtime_collector_failure_does_not_break_metrics_scrape() -> None:
    def unavailable_snapshot():
        raise RuntimeError("SECRET DATABASE URL")

    families = _families(ProductRuntimeCollector(unavailable_snapshot))

    assert families["qatth_runtime_metrics_scrape_success"].samples[0].value == 0
    assert "SECRET DATABASE URL" not in repr(families)


def test_runtime_collector_registration_is_idempotent() -> None:
    registry = CollectorRegistry()

    register_product_metrics(registry)
    register_product_metrics(registry)

    names = [family.name for family in registry.collect()]
    assert names.count("qatth_runtime_metrics_scrape_success") == 1
