from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend import database


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "api_test.db")
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_demo_auth_protects_application_routes_but_not_health(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_AUTH_REQUIRED", "true")
    monkeypatch.setenv("DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass")

    health = client.get("/health")
    unauthenticated = client.get("/")
    authenticated = client.get("/", auth=("demo-user", "demo-pass"))

    assert health.status_code == 200
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"].startswith("Basic ")
    assert authenticated.status_code == 200


def test_demo_auth_fails_closed_when_credentials_are_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_AUTH_REQUIRED", "true")

    response = client.get("/api/customers")

    assert response.status_code == 503
    assert response.json() == {"detail": "Demo access is not configured"}


def test_demo_auth_is_disabled_by_default_locally(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("DEMO_AUTH_REQUIRED", raising=False)

    response = client.get("/api/customers")

    assert response.status_code == 200


def test_render_environment_requires_auth_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DEMO_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass")

    response = client.get("/api/customers")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")


def test_render_environment_ignores_explicit_auth_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DEMO_AUTH_REQUIRED", "false")
    monkeypatch.setenv("DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass")

    response = client.get("/api/customers")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")


def test_demo_auth_rejects_invalid_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_AUTH_REQUIRED", "true")
    monkeypatch.setenv("DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass")

    response = client.get("/api/customers", auth=("demo-user", "wrong-pass"))

    assert response.status_code == 401


def test_root_serves_production_frontend_entry_point(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>production app</html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == "<html>production app</html>"


def test_static_production_assets_are_served_from_build_directory(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (assets / "app-deadbeef.js").write_text("built asset", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

    response = client.get("/assets/app-deadbeef.js")

    assert response.status_code == 200
    assert response.text == "built asset"
    assert "javascript" in response.headers["content-type"]


def test_unknown_browser_navigation_receives_frontend_entry_point(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app shell</html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

    response = client.get("/customers/42", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert response.text == "<html>app shell</html>"
    assert response.headers["content-type"].startswith("text/html")


def test_existing_api_routes_remain_api_responses(client: TestClient) -> None:
    health = client.get("/health")
    customers = client.get("/api/customers")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert customers.status_code == 200
    assert customers.headers["content-type"].startswith("application/json")
    assert customers.json() == {"customers": []}


def test_unknown_api_paths_never_fall_through_to_frontend_html(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app shell</html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

    response = client.get("/api/does-not-exist", headers={"accept": "text/html"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html>" not in response.text


def test_missing_frontend_build_retains_safe_root_behavior(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_dist = tmp_path / "missing-dist"
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", missing_dist)

    root = client.get("/")
    navigation = client.get("/not-built", headers={"accept": "text/html"})

    assert root.status_code == 200
    assert root.json() == {"message": "Kirana Voice Khata API is running"}
    assert navigation.status_code == 404
    assert navigation.headers["content-type"].startswith("application/json")
