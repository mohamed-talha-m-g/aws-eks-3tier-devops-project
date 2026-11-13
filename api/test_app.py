"""Unit tests that run without a database (used by the CI pipeline)."""
import os

os.environ["SKIP_DB_INIT"] = "1"  # must be set before importing app

import app as app_module  # noqa: E402
from app import app  # noqa: E402


def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_health_returns_ok():
    resp = client().get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_info_reports_version_and_hostname():
    body = client().get("/api/info").get_json()
    assert "version" in body and "hostname" in body


def test_create_task_rejects_empty_title():
    resp = client().post("/api/tasks", json={"title": "   "})
    assert resp.status_code == 400


def test_ready_returns_503_without_database(monkeypatch):
    # Point the app at a port where nothing listens, so the DB check must fail.
    monkeypatch.setitem(app_module.DB_CONFIG, "port", 1)
    resp = client().get("/api/ready")
    assert resp.status_code == 503
