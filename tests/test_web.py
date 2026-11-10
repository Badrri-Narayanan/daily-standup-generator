import pytest
from conftest import ticket
from fastapi.testclient import TestClient

from standup_generator.config import AppConfig, HistoryConfig
from standup_generator.models import SourceResult
from standup_generator.web.app import create_app


class Fake:
    name = "fake"

    def collect(self, w):
        return SourceResult("fake", tickets=[ticket("OFF-1")], errors=["fake: partial"])


@pytest.fixture
def cfg(tmp_path):
    return AppConfig(history=HistoryConfig(db_path=tmp_path / "h.db"))


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg, sources=[Fake()]), base_url="http://127.0.0.1")


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Generate" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_window_endpoint(client):
    r = client.get("/api/window", params={"since": "2026-11-02"})
    assert r.json()["start"].startswith("2026-11-02")


def test_generate_returns_id_and_prompt(client):
    r = client.post("/api/generate", json={"plans": "ship OFF-1", "blockers": ""})
    body = r.json()
    assert r.status_code == 200 and body["id"] == 1
    assert "ship OFF-1" in body["prompt"]
    assert body["errors"] == {"fake": ["fake: partial"]}
    assert body["collected"]["in_progress"][0]["ticket"]["key"] == "OFF-1"
    assert "start" in body["window"]


def test_patch_final_then_get(client):
    i = client.post("/api/generate", json={}).json()["id"]
    assert client.patch(f"/api/history/{i}", json={"final_standup": "Yesterday: OFF-1"}).status_code == 200
    entry = client.get(f"/api/history/{i}").json()
    assert entry["final_standup"] == "Yesterday: OFF-1" and "## Instructions" in entry["prompt"]


def test_history_list_and_delete(client):
    a = client.post("/api/generate", json={}).json()["id"]
    b = client.post("/api/generate", json={}).json()["id"]
    assert [h["id"] for h in client.get("/api/history").json()] == [b, a]
    assert client.delete(f"/api/history/{a}").status_code == 204
    assert [h["id"] for h in client.get("/api/history").json()] == [b]


def test_missing_entries_404(client):
    assert client.get("/api/history/99").status_code == 404
    assert client.patch("/api/history/99", json={"final_standup": "x"}).status_code == 404
    assert client.delete("/api/history/99").status_code == 404


def test_bad_host_rejected(cfg):
    evil = TestClient(create_app(cfg, sources=[Fake()]), base_url="http://evil.com")
    assert evil.get("/api/history").status_code == 400


def test_localhost_with_port_allowed(cfg):
    c = TestClient(create_app(cfg, sources=[Fake()]), base_url="http://localhost:8765")
    assert c.get("/api/history").status_code == 200


def test_history_disabled_404(cfg):
    cfg.history.enabled = False
    c = TestClient(create_app(cfg, sources=[Fake()]), base_url="http://127.0.0.1")
    r = c.post("/api/generate", json={})
    assert r.status_code == 200 and r.json()["id"] is None
    resp = c.get("/api/history")
    assert resp.status_code == 404 and resp.json()["detail"] == "history disabled"
