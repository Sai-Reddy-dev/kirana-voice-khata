import pytest


@pytest.fixture(autouse=True)
def isolate_deployment_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "DATABASE_PATH",
        "DEMO_AUTH_REQUIRED",
        "DEMO_USERNAME",
        "DEMO_PASSWORD",
        "RENDER",
    ):
        monkeypatch.delenv(variable, raising=False)
