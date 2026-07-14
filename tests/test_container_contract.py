from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_image_and_compose_expose_backend_owned_process_contract() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert "USER qatth" in dockerfile
    assert "--timeout-graceful-shutdown" in dockerfile
    assert {"migrate", "api", "worker", "beat", "minio-init"}.issubset(services)
    assert services["migrate"]["command"] == "alembic upgrade head"
    assert " worker " in " " + services["worker"]["command"] + " "
    assert " beat " in " " + services["beat"]["command"] + " "
    assert services["api"]["healthcheck"]["test"][-1].endswith("/health/ready")
    assert services["api"]["depends_on"]["minio-init"]["condition"] == "service_completed_successfully"


def test_compose_uses_the_same_object_storage_contract_as_settings() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    for service_name in ("api", "worker"):
        environment = compose["services"][service_name]["environment"]
        assert environment["STORAGE_BACKEND"] == "minio"
        assert environment["R2_ENDPOINT_URL"] == "http://minio:9000"
        assert {"R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"}.issubset(environment)
        assert not any(key.startswith("MINIO_") for key in environment)

    example = (ROOT / ".env.example").read_text()
    assert "MINIO_" not in example
