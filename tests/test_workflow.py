from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Message, Reminder, User
from app.repository import auto_fail_overdue_tasks, confirm_plan, due_reminders, ensure_rollover_prompt, expire_stale_drafts, get_or_create_conversation, learning_progress_summary, save_generated_plan, set_task_result, submit_quiz, supersede_plan
from app.schemas import GeneratedPlan, LearningOutput, QuizQuestion, TaskDraft


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(User(id=1))
    session.commit()
    return session


def make_plan() -> GeneratedPlan:
    start = datetime.now() - timedelta(hours=2)
    learning = LearningOutput(
        task_title="学习测试",
        learning_goal="验证学习闭环",
        material_summary="测试摘要",
        completion_criteria="完成自测",
        suggested_start=start.strftime("%H:%M"),
        quiz=[
            QuizQuestion(question=f"问题{i}", options=["A", "B", "C", "D"], correct_index=i % 4, explanation="解析")
            for i in range(3)
        ],
    )
    return GeneratedPlan(
        request_id="request-1",
        target_date=date.today().isoformat(),
        tasks=[
            TaskDraft(
                owner_agent="learning",
                task_type="learning",
                title="学习测试",
                description="完成自测",
                location="北京",
                priority="medium",
                start_at=start,
                due_at=start + timedelta(hours=1),
                estimated_minutes=60,
            )
        ],
        learning=learning,
    )


def test_confirmation_is_idempotent_and_creates_one_reminder():
    session = make_session()
    plan = save_generated_plan(session, make_plan())
    confirm_plan(session, plan.id)
    confirm_plan(session, plan.id)
    session.commit()
    assert session.scalar(select(func.count()).select_from(Reminder)) == 1


def test_due_reminder_is_shown_only_for_open_task():
    session = make_session()
    plan = save_generated_plan(session, make_plan())
    confirm_plan(session, plan.id)
    session.commit()
    reminders = due_reminders(session, datetime.now())
    assert len(reminders) == 1
    assert reminders[0][0].attempt_count == 1


def test_overdue_task_is_auto_failed_and_reminder_is_dismissed():
    session = make_session()
    plan = save_generated_plan(session, make_plan())
    confirm_plan(session, plan.id)
    session.commit()

    overdue = auto_fail_overdue_tasks(session, datetime.now())
    session.commit()

    assert [task.id for task in overdue] == [plan.tasks[0].id]
    assert plan.tasks[0].status == "NOT_COMPLETED"
    assert plan.tasks[0].not_completed_reason == "超过截止时间未完成"
    assert session.scalar(select(Reminder.status)) == "DISMISSED"
    assert auto_fail_overdue_tasks(session, datetime.now()) == []


def test_quiz_submission_scores_and_completes_task():
    session = make_session()
    plan = save_generated_plan(session, make_plan())
    confirm_plan(session, plan.id)
    record = plan.tasks[0].learning_record
    result = submit_quiz(session, record.id, [0, 1, 3])
    assert result.score == 2
    assert result.mastery_level == "基本掌握"
    assert result.task.status == "COMPLETED"
    summary = learning_progress_summary(session)
    assert summary["total"] == 1
    assert summary["assessed"] == 1
    assert summary["average_score"] == 2.0


def test_rollover_prompt_is_created_once_without_moving_history():
    session = make_session()
    yesterday = date.today() - timedelta(days=1)
    generated = make_plan()
    generated.target_date = yesterday.isoformat()
    generated.tasks[0].start_at = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=9)
    generated.tasks[0].due_at = generated.tasks[0].start_at + timedelta(hours=1)
    plan = save_generated_plan(session, generated)
    confirm_plan(session, plan.id)
    set_task_result(session, plan.tasks[0].id, False, "时间不足")
    conversation = get_or_create_conversation(session)

    assert ensure_rollover_prompt(session, conversation.id, date.today()) is not None
    assert ensure_rollover_prompt(session, conversation.id, date.today()) is None
    assert session.scalar(select(func.count()).select_from(Message)) == 1
    assert plan.tasks[0].start_at.date() == yesterday
    assert plan.tasks[0].status == "NOT_COMPLETED"


def test_old_draft_is_expired_and_current_draft_can_be_superseded():
    session = make_session()
    old_plan = make_plan()
    old_plan.target_date = (date.today() - timedelta(days=1)).isoformat()
    saved_old = save_generated_plan(session, old_plan)
    session.commit()
    assert expire_stale_drafts(session, date.today()) == 1
    assert saved_old.status == "EXPIRED"

    current_plan = make_plan().model_copy(update={"request_id": "request-current"})
    saved_current = save_generated_plan(session, current_plan)
    supersede_plan(session, saved_current.id)
    session.commit()
    assert saved_current.status == "SUPERSEDED"
