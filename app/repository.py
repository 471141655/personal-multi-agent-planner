from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.models import AgentRun, Conversation, DailyReview, LearningRecord, Message, Plan, Reminder, Task, TaskChangeLog
from app.schemas import GeneratedPlan, ReviewOutput, TaskDraft
from app.timeutils import now_local


def save_generated_plan(session: Session, generated: GeneratedPlan, user_id: int = 1, input_summary: str = "") -> Plan:
    existing = session.scalar(select(Plan).where(Plan.request_id == generated.request_id))
    if existing:
        return existing
    plan = Plan(
        user_id=user_id,
        request_id=generated.request_id,
        status="WAITING_CONFIRMATION",
        target_date=date.fromisoformat(generated.target_date),
        conflict_summary=generated.conflicts,
    )
    session.add(plan)
    session.flush()
    learning_task: Task | None = None
    for item in generated.tasks:
        task = Task(
            plan_id=plan.id,
            owner_agent=item.owner_agent,
            task_type=item.task_type,
            title=item.title,
            description=item.description,
            location=item.location,
            priority=item.priority,
            start_at=item.start_at,
            due_at=item.due_at,
            estimated_minutes=item.estimated_minutes,
            status="PENDING",
        )
        session.add(task)
        session.flush()
        if item.task_type == "learning" and learning_task is None:
            learning_task = task
    if learning_task and generated.learning:
        session.add(
            LearningRecord(
                task_id=learning_task.id,
                topic=generated.learning.task_title,
                learning_goal=generated.learning.learning_goal,
                material_summary=generated.learning.material_summary,
                completion_criteria=generated.learning.completion_criteria,
                sources_json=[item.model_dump(mode="json") for item in generated.news],
                quiz_json=[item.model_dump(mode="json") for item in generated.learning.quiz],
            )
        )
    for run in generated.agent_runs:
        session.add(
            AgentRun(
                request_id=generated.request_id,
                agent_name=run["agent_name"],
                input_summary=input_summary[:500],
                output_json=run.get("output_json", {}),
                status=run["status"],
                retry_count=run.get("retry_count", 0),
                duration_ms=run.get("duration_ms", 0),
                error_code=run.get("error_code"),
            )
        )
    session.flush()
    return plan


def get_or_create_conversation(session: Session, user_id: int = 1) -> Conversation:
    conversation = session.scalar(select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).limit(1))
    if conversation is None:
        conversation = Conversation(user_id=user_id)
        session.add(conversation)
        session.flush()
    return conversation


def add_message(session: Session, conversation_id: int, role: str, content: str) -> Message:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError("对话不存在")
    message = Message(conversation_id=conversation_id, role=role, content=content)
    conversation.updated_at = now_local()
    session.add(message)
    session.flush()
    return message


def recent_messages(session: Session, conversation_id: int, limit: int = 12) -> list[Message]:
    rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(limit)))
    rows.reverse()
    return rows


def latest_draft(session: Session, user_id: int = 1) -> Plan | None:
    return session.scalar(
        select(Plan)
        .options(selectinload(Plan.tasks).selectinload(Task.learning_record))
        .where(Plan.user_id == user_id, Plan.status == "WAITING_CONFIRMATION")
        .order_by(Plan.created_at.desc())
        .limit(1)
    )


def expire_stale_drafts(session: Session, before_date: date, user_id: int = 1) -> int:
    plans = list(
        session.scalars(
            select(Plan).where(
                Plan.user_id == user_id,
                Plan.status == "WAITING_CONFIRMATION",
                Plan.target_date < before_date,
            )
        )
    )
    for plan in plans:
        plan.status = "EXPIRED"
    session.flush()
    return len(plans)


def supersede_plan(session: Session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if not plan:
        raise ValueError("计划不存在")
    if plan.status == "WAITING_CONFIRMATION":
        plan.status = "SUPERSEDED"
        session.flush()
    return plan


def get_plan(session: Session, plan_id: int) -> Plan | None:
    return session.scalar(select(Plan).options(selectinload(Plan.tasks).selectinload(Task.learning_record)).where(Plan.id == plan_id))


def update_draft_task(session: Session, task_id: int, values: dict) -> Task:
    task = session.get(Task, task_id)
    if not task or task.plan.status != "WAITING_CONFIRMATION":
        raise ValueError("只能直接修改未确认的计划草稿")
    before = task_snapshot(task)
    for field in ["title", "start_at", "due_at", "estimated_minutes", "priority"]:
        if field in values:
            setattr(task, field, values[field])
    task.updated_at = now_local()
    session.add(TaskChangeLog(task_id=task.id, change_source="USER_DRAFT_EDIT", before_json=before, after_json=task_snapshot(task), confirmed_by_user=True))
    session.flush()
    return task


def replace_plan_conflicts(session: Session, plan: Plan, conflicts: list[str]) -> None:
    plan.conflict_summary = conflicts
    session.flush()


def confirm_plan(session: Session, plan_id: int) -> Plan:
    plan = get_plan(session, plan_id)
    if not plan:
        raise ValueError("计划不存在")
    if plan.status == "CONFIRMED":
        return plan
    blocking = [item for item in (plan.conflict_summary or []) if not item.startswith("工具提示：")]
    if blocking:
        raise ValueError("请先解决计划中的时间冲突")
    plan.status = "CONFIRMED"
    plan.confirmed_at = now_local()
    for task in plan.tasks:
        task.status = "CONFIRMED"
        existing = session.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.reminder_type == "OVERDUE", Reminder.scheduled_at == task.due_at))
        if not existing:
            session.add(Reminder(task_id=task.id, scheduled_at=task.due_at, reminder_type="OVERDUE", status="PENDING"))
    session.flush()
    return plan


def tasks_for_day(session: Session, target_date: date, user_id: int = 1) -> list[Task]:
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    return list(
        session.scalars(
            select(Task)
            .join(Plan)
            .options(selectinload(Task.learning_record))
            .where(Plan.user_id == user_id, Plan.status == "CONFIRMED", Task.start_at >= start, Task.start_at < end)
            .order_by(Task.start_at)
        )
    )


def set_task_result(session: Session, task_id: int, completed: bool, reason: str | None = None) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise ValueError("任务不存在")
    if completed:
        task.status = "COMPLETED"
        task.completed_at = now_local()
        task.not_completed_reason = None
    else:
        if not reason:
            raise ValueError("未完成任务必须填写原因")
        task.status = "NOT_COMPLETED"
        task.not_completed_reason = reason
        task.completed_at = None
    task.updated_at = now_local()
    session.flush()
    return task


def submit_quiz(session: Session, record_id: int, answers: list[int]) -> LearningRecord:
    record = session.get(LearningRecord, record_id)
    if not record:
        raise ValueError("学习记录不存在")
    quiz = record.quiz_json or []
    if len(answers) != len(quiz):
        raise ValueError("请完成全部题目")
    score = sum(int(answer == int(question["correct_index"])) for answer, question in zip(answers, quiz))
    record.answers_json = answers
    record.score = score
    record.mastery_level = "已掌握" if score == 3 else "基本掌握" if score == 2 else "需要复习"
    record.submitted_at = now_local()
    record.task.status = "COMPLETED"
    record.task.completed_at = now_local()
    session.flush()
    return record


def due_reminders(session: Session, now: datetime | None = None) -> list[tuple[Reminder, Task]]:
    now = now or now_local()
    rows = session.execute(
        select(Reminder, Task)
        .join(Task, Task.id == Reminder.task_id)
        .where(
            Reminder.status.in_(["PENDING", "SHOWN"]),
            Reminder.attempt_count < 3,
            Reminder.scheduled_at <= now,
            Task.status.notin_(["COMPLETED", "NOT_COMPLETED", "CANCELLED"]),
            (Reminder.snoozed_until.is_(None) | (Reminder.snoozed_until <= now)),
        )
        .order_by(Reminder.scheduled_at)
    ).all()
    for reminder, _ in rows:
        if reminder.status == "PENDING":
            reminder.status = "SHOWN"
            reminder.attempt_count += 1
    session.flush()
    return rows


def auto_fail_overdue_tasks(session: Session, now: datetime | None = None) -> list[Task]:
    now = now or now_local()
    rows = session.execute(
        select(Reminder, Task)
        .join(Task, Task.id == Reminder.task_id)
        .where(
            Reminder.status.in_(["PENDING", "SHOWN"]),
            Reminder.scheduled_at <= now,
            Task.status.notin_(["COMPLETED", "NOT_COMPLETED", "CANCELLED"]),
        )
        .order_by(Reminder.scheduled_at)
    ).all()
    overdue: list[Task] = []
    for reminder, task in rows:
        task.status = "NOT_COMPLETED"
        task.not_completed_reason = "超过截止时间未完成"
        task.completed_at = None
        task.updated_at = now
        reminder.status = "DISMISSED"
        reminder.snoozed_until = None
        overdue.append(task)
    session.flush()
    return overdue


def snooze_reminder(session: Session, reminder_id: int, minutes: int) -> None:
    reminder = session.get(Reminder, reminder_id)
    if reminder and reminder.attempt_count < 3:
        reminder.status = "PENDING"
        reminder.snoozed_until = now_local() + timedelta(minutes=minutes)
        session.flush()


def dismiss_reminder(session: Session, reminder_id: int) -> None:
    reminder = session.get(Reminder, reminder_id)
    if reminder:
        reminder.status = "DISMISSED"
        session.flush()


def build_review_facts(tasks: list[Task]) -> dict:
    completed = [task for task in tasks if task.status == "COMPLETED"]
    reasons = [task.not_completed_reason for task in tasks if task.not_completed_reason]
    learning = []
    for task in tasks:
        if task.learning_record:
            learning.append({"title": task.title, "score": task.learning_record.score, "mastery": task.learning_record.mastery_level})
    return {
        "total": len(tasks),
        "completed": len(completed),
        "completion_rate": round(len(completed) / len(tasks) * 100, 1) if tasks else 0,
        "reasons": reasons,
        "learning": learning,
        "tasks": [{"title": task.title, "status": task.status, "reason": task.not_completed_reason} for task in tasks],
    }


def upsert_review(session: Session, target_date: date, output: ReviewOutput, facts: dict, user_id: int = 1) -> DailyReview:
    review = session.scalar(select(DailyReview).where(DailyReview.user_id == user_id, DailyReview.review_date == target_date))
    payload = {"wins": output.wins, "issues": output.issues, "suggestions": output.suggestions, "facts": facts}
    if review:
        review.summary = output.summary
        review.details_json = payload
        review.updated_at = now_local()
    else:
        review = DailyReview(user_id=user_id, review_date=target_date, summary=output.summary, details_json=payload)
        session.add(review)
    session.flush()
    return review


def review_for_day(session: Session, target_date: date, user_id: int = 1) -> DailyReview | None:
    return session.scalar(select(DailyReview).where(DailyReview.user_id == user_id, DailyReview.review_date == target_date))


def latest_agent_runs(session: Session, limit: int = 8) -> list[AgentRun]:
    return list(session.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)))


def task_snapshot(task: Task) -> dict:
    return {
        "title": task.title,
        "start_at": task.start_at.isoformat(),
        "due_at": task.due_at.isoformat(),
        "estimated_minutes": task.estimated_minutes,
        "priority": task.priority,
        "status": task.status,
    }
