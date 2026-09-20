from datetime import date, datetime, timedelta

import app.agents as agents
from app.agents import PlannerOrchestrator, detect_conflicts
from app.llm import ModelUnavailable
from app.auth import hash_password
from app.conversation import assess_plan_request, is_new_plan_request, is_plan_confirmation, parse_plan_change
from app.database import normalize_database_url
from app.schemas import TaskDraft


def task(title: str, start_hour: int, end_hour: int) -> TaskDraft:
    day = date(2026, 9, 18)
    return TaskDraft(
        owner_agent="learning",
        task_type="learning",
        title=title,
        description="",
        location="北京",
        priority="medium",
        start_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=start_hour),
        due_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=end_hour),
        estimated_minutes=(end_hour - start_hour) * 60,
    )


def test_detects_overlap():
    conflicts = detect_conflicts([task("A", 19, 21), task("B", 20, 22)])
    assert any("时间重叠" in conflict for conflict in conflicts)


def test_valid_schedule_has_no_conflict():
    assert detect_conflicts([task("A", 19, 20), task("B", 21, 22)]) == []


def test_database_url_normalization():
    assert normalize_database_url("postgresql://example/db") == "postgresql+psycopg://example/db"
    assert normalize_database_url("sqlite:///data/app.db") == "sqlite:///data/app.db"


def test_password_hash_is_stable():
    assert hash_password("secret") == hash_password("secret")
    assert hash_password("secret") != hash_password("different")


class UnavailableClient:
    def structured(self, *args, **kwargs):
        raise ModelUnavailable("test fallback")


def test_weekend_fallback_keeps_all_tasks_and_explicit_duration(monkeypatch):
    target_day = date(2026, 9, 20)  # Sunday
    monkeypatch.setattr(agents, "_today", lambda: target_day)
    monkeypatch.setattr(agents, "now_local", lambda: datetime(2026, 9, 20, 8, 0))
    monkeypatch.setattr(agents, "fetch_ai_news", lambda: ([], []))
    monkeypatch.setattr(agents, "fetch_weather", lambda *args: {"city": "北京", "condition": "晴", "precipitation_probability": 0})
    updates = []

    plan = PlannerOrchestrator(client=UnavailableClient()).generate(
        "今天是周末，我打算完善我的智能工作台，学习了解AI最新资讯，还有完善回忆录软件系统的语音转文字转剧本的功能模块，还想运动2小时",
        progress=lambda agent, message: updates.append((agent, message)),
    )

    titles = [task.title for task in plan.tasks]
    assert any("智能工作台" in title for title in titles)
    assert any("回忆录软件系统" in title for title in titles)
    assert any(task.task_type == "learning" for task in plan.tasks)
    exercise = next(task for task in plan.tasks if task.task_type == "life")
    assert exercise.estimated_minutes == 120
    assert exercise.start_at.hour != 19
    assert len(plan.tasks) == 4
    assert any(agent == "scheduler" for agent, _ in updates)


def test_short_or_ambiguous_input_does_not_generate_plan():
    assert assess_plan_request("我")[0] is False
    assert assess_plan_request("你好")[0] is False
    assert assess_plan_request("随便聊聊")[0] is False
    assert assess_plan_request("今天学习 AI 资讯 1 小时")[0] is True


def test_conversational_confirmation_and_plan_change():
    tasks = [
        {
            "id": 10,
            "title": "完成 2 小时运动",
            "start": datetime(2026, 9, 20, 14, 0),
            "due": datetime(2026, 9, 20, 16, 0),
            "minutes": 120,
            "priority": "low",
        }
    ]
    assert is_plan_confirmation("确认计划") is True
    task_id, changes, clarification = parse_plan_change("把运动改到晚上8点，时长1小时", tasks)
    assert clarification == ""
    assert task_id == 10
    assert changes["estimated_minutes"] == 60
    assert changes["start_at"] == datetime(2026, 9, 20, 20, 0)
    assert changes["due_at"] == datetime(2026, 9, 20, 21, 0)
    assert is_new_plan_request("今天重新安排学习 Python 和运动一小时") is True
    assert is_new_plan_request("把运动改成一小时") is False
