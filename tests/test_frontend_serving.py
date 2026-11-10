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
