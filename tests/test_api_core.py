import asyncio
import threading

from fastapi.testclient import TestClient

from app.api import app, login_failures
from app.auth import issue_access_token, verify_access_token
from app.jobs import JobManager
import app.worker as worker_module


def test_access_token_round_trip_and_tamper(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("APP_PASSWORD_HASH", "")
    token = issue_access_token(user_id=1)
    assert verify_access_token(token) == 1
    assert verify_access_token(token + "x") is None
    assert verify_access_token("not-a-token") is None
    assert verify_access_token("%%%%.%%%%") is None


def test_job_manager_replays_events_and_completes():
    async def scenario():
        manager = JobManager()
        job = manager.create("plan")
        await manager.publish(job.id, "started", {"agent": "leader"})
        await manager.publish(job.id, "completed", {"plan_id": 7})
        events = [event async for event in manager.stream(job.id)]
        assert [event.event for event in events] == ["started", "completed"]
        assert events[-1].data["plan_id"] == 7

    asyncio.run(scenario())


def test_login_rate_limit_and_security_headers():
    login_failures.clear()


def test_embedded_worker_starts_only_once(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def fake_worker():
        started.set()
        release.wait(timeout=1)

    monkeypatch.setattr(worker_module, "run_forever", fake_worker)
    monkeypatch.setattr(worker_module, "_embedded_thread", None)
    first = worker_module.start_embedded_worker()
    assert started.wait(timeout=1)
    second = worker_module.start_embedded_worker()
    release.set()
    first.join(timeout=1)
    assert second is first
    client = TestClient(app)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "definitely-wrong"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"password": "definitely-wrong"})
    assert blocked.status_code == 429
    health = client.get("/api/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    login_failures.clear()
