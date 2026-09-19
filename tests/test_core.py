from datetime import date, datetime, timedelta

from app.agents import detect_conflicts
from app.auth import hash_password
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

