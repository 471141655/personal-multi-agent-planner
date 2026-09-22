import asyncio

from app.auth import issue_access_token, verify_access_token
from app.jobs import JobManager


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
