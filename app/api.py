from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Callable

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agents import PlannerOrchestrator, detect_conflicts
from app.auth import issue_access_token, verify_access_token, verify_password
from app.config import get_settings
from app.conversation import (
    assess_plan_request,
    encouraging_summary,
    is_new_plan_request,
    is_plan_confirmation,
    is_review_request,
    parse_plan_change,
    plan_text,
    schedule_basis,
    schedule_clarification,
)
from app.database import init_db, session_scope
from app.feishu import feishu_client
from app.jobs import job_manager
from app.repository import (
    add_message,
    build_review_facts,
    confirm_plan,
    get_channel_state,
    get_or_create_conversation,
    get_plan,
    latest_draft,
    learning_progress_summary,
    mark_channel_event_processed,
    recent_messages,
    record_channel_event,
    replace_plan_conflicts,
    save_generated_plan,
    set_channel_pending_request,
    set_task_result,
    submit_quiz,
    supersede_plan,
    tasks_for_day,
    update_draft_task,
    upsert_review,
)
from app.schemas import TaskDraft
from app.timeutils import today_local
from app.worker import start_embedded_worker


settings = get_settings()
app = FastAPI(title="Personal Multi-Agent Planner API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.frontend_origins.split(",") if item.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
security = HTTPBearer(auto_error=False)
login_failures: dict[str, deque[float]] = defaultdict(deque)
login_failure_lock = threading.Lock()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.on_event("startup")
def startup() -> None:
    init_db()
    if settings.run_embedded_worker:
        start_embedded_worker()


class LoginRequest(BaseModel):
    password: str


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    pending_request: str | None = Field(default=None, max_length=5000)


class TaskResultRequest(BaseModel):
    completed: bool
    reason: str | None = None


class QuizSubmission(BaseModel):
    answers: list[int]


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> int:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user_id = verify_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user_id


def plan_rows(plan) -> list[dict]:
    return [
        {
            "id": task.id,
            "title": task.title,
            "start": task.start_at,
            "due": task.due_at,
            "minutes": task.estimated_minutes,
            "priority": task.priority,
        }
        for task in plan.tasks
    ]


def serialize_task(task) -> dict:
    learning = None
    if task.learning_record:
        record = task.learning_record
        learning = {
            "id": record.id,
            "topic": record.topic,
            "goal": record.learning_goal,
            "material_summary": record.material_summary,
            "completion_criteria": record.completion_criteria,
            "sources": record.sources_json or [],
            "quiz": [{"question": item["question"], "options": item["options"]} for item in (record.quiz_json or [])],
            "score": record.score,
            "mastery": record.mastery_level,
        }
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "type": task.task_type,
        "owner_agent": task.owner_agent,
        "location": task.location,
        "priority": task.priority,
        "start_at": task.start_at.isoformat(),
        "due_at": task.due_at.isoformat(),
        "estimated_minutes": task.estimated_minutes,
        "status": task.status,
        "not_completed_reason": task.not_completed_reason,
        "learning": learning,
    }


def serialize_plan(plan) -> dict:
    return {
        "id": plan.id,
        "status": plan.status,
        "target_date": plan.target_date.isoformat(),
        "conflicts": list(plan.conflict_summary or []),
        "tasks": [serialize_task(task) for task in plan.tasks],
    }


def save_assistant(conversation_id: int, content: str) -> dict:
    with session_scope() as session:
        message = add_message(session, conversation_id, "assistant", content)
        return {"id": message.id, "role": message.role, "content": message.content, "created_at": message.created_at.isoformat()}


def generate_plan_sync(
    request_text: str,
    conversation_id: int,
    supersede_plan_id: int | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> dict:
    generated = PlannerOrchestrator().generate(request_text, progress=progress)
    with session_scope() as session:
        if supersede_plan_id:
            supersede_plan(session, supersede_plan_id)
        plan = save_generated_plan(session, generated, input_summary=request_text)
        rows = plan_rows(plan)
        assistant_text = plan_text(rows)
        basis = schedule_basis(request_text)
        if basis:
            assistant_text += "\n\n排期依据：\n" + "\n".join(f"- {item}" for item in basis)
        if generated.conflicts:
            assistant_text += "\n\n提示：\n" + "\n".join(f"- {item}" for item in generated.conflicts)
        add_message(session, conversation_id, "assistant", assistant_text)
        return {"plan": serialize_plan(plan), "message": assistant_text}


def generate_review_sync(conversation_id: int, target_date: date) -> dict:
    with session_scope() as session:
        facts = build_review_facts(tasks_for_day(session, target_date))
    output = PlannerOrchestrator().review(facts)
    text = (
        f"📝 Review Agent · {target_date.isoformat()} 复盘\n\n{output.summary}\n\n"
        + "做得好的地方\n"
        + "\n".join(f"- {item}" for item in output.wins)
        + "\n\n主要问题\n"
        + "\n".join(f"- {item}" for item in output.issues)
        + "\n\n下一步建议\n"
        + "\n".join(f"- {item}" for item in output.suggestions)
    )
    with session_scope() as session:
        upsert_review(session, target_date, output, facts)
        add_message(session, conversation_id, "assistant", text)
    return {"review": output.model_dump(mode="json"), "message": text}


async def run_plan_job(job_id: str, request_text: str, conversation_id: int, supersede_plan_id: int | None) -> None:
    loop = asyncio.get_running_loop()
    await job_manager.publish(job_id, "started", {"agent": "leader", "message": "正在解析需求"})

    def progress(agent: str, message: str) -> None:
        asyncio.run_coroutine_threadsafe(job_manager.publish(job_id, "progress", {"agent": agent, "message": message}), loop)

    try:
        result = await asyncio.to_thread(generate_plan_sync, request_text, conversation_id, supersede_plan_id, progress)
        await job_manager.publish(job_id, "completed", result)
    except Exception as exc:
        await job_manager.publish(job_id, "failed", {"message": str(exc)})


async def run_review_job(job_id: str, conversation_id: int, target_date: date) -> None:
    await job_manager.publish(job_id, "started", {"agent": "review", "message": "正在读取任务记录"})
    try:
        result = await asyncio.to_thread(generate_review_sync, conversation_id, target_date)
        await job_manager.publish(job_id, "completed", result)
    except Exception as exc:
        await job_manager.publish(job_id, "failed", {"message": str(exc)})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request) -> dict:
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with login_failure_lock:
        failures = login_failures[client_key]
        while failures and now - failures[0] > settings.login_window_seconds:
            failures.popleft()
        if len(failures) >= settings.login_max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录失败次数过多，请稍后再试",
                headers={"Retry-After": str(settings.login_window_seconds)},
            )
    if not verify_password(payload.password):
        with login_failure_lock:
            login_failures[client_key].append(now)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密码错误")
    with login_failure_lock:
        login_failures.pop(client_key, None)
    return {"access_token": issue_access_token(), "token_type": "bearer"}


@app.get("/api/dashboard")
def dashboard(target_date: date | None = None, user_id: int = Depends(current_user)) -> dict:
    selected = target_date or today_local()
    with session_scope() as session:
        conversation = get_or_create_conversation(session, user_id)
        tasks = tasks_for_day(session, selected, user_id)
        messages = recent_messages(session, conversation.id, limit=50)
        draft = latest_draft(session, user_id)
        progress = learning_progress_summary(session, user_id)
        return {
            "selected_date": selected.isoformat(),
            "today": today_local().isoformat(),
            "tasks": [serialize_task(task) for task in tasks],
            "messages": [
                {"id": item.id, "role": item.role, "content": item.content, "created_at": item.created_at.isoformat()}
                for item in messages
            ],
            "draft": serialize_plan(draft) if draft else None,
            "learning_summary": progress,
        }


@app.post("/api/chat")
async def chat(payload: ChatRequest, user_id: int = Depends(current_user)) -> dict:
    prompt = payload.text.strip()
    with session_scope() as session:
        conversation = get_or_create_conversation(session, user_id)
        conversation_id = conversation.id
        add_message(session, conversation_id, "user", prompt)
        draft = latest_draft(session, user_id)

    if is_review_request(prompt):
        job = job_manager.create("review")
        asyncio.create_task(run_review_job(job.id, conversation_id, today_local()))
        return {"action": "job", "job_id": job.id, "kind": "review"}

    if payload.pending_request:
        if prompt in {"取消", "不用了", "算了"}:
            message = save_assistant(conversation_id, "已取消这次计划生成。")
            return {"action": "message", "message": message}
        combined = f"{payload.pending_request}\n补充信息：{prompt}"
        job = job_manager.create("plan")
        asyncio.create_task(run_plan_job(job.id, combined, conversation_id, draft.id if draft else None))
        return {"action": "job", "job_id": job.id, "kind": "plan"}

    if draft and is_plan_confirmation(prompt):
        blocking = [item for item in (draft.conflict_summary or []) if not item.startswith("工具提示：")]
        if blocking:
            message = save_assistant(conversation_id, "当前计划仍有冲突：\n" + "\n".join(f"- {item}" for item in blocking))
            return {"action": "message", "message": message}
        with session_scope() as session:
            plan = get_plan(session, draft.id)
            rows = plan_rows(plan)
            confirm_plan(session, plan.id)
            message = add_message(session, conversation_id, "assistant", encouraging_summary(rows))
            return {
                "action": "confirmed",
                "target_date": plan.target_date.isoformat(),
                "message": {"id": message.id, "role": message.role, "content": message.content, "created_at": message.created_at.isoformat()},
            }

    if draft and not is_new_plan_request(prompt):
        task_id, changes, clarification = parse_plan_change(prompt, plan_rows(draft))
        if not changes:
            message = save_assistant(conversation_id, clarification)
            return {"action": "message", "message": message}
        with session_scope() as session:
            update_draft_task(session, task_id, changes)
            refreshed = latest_draft(session, user_id)
            drafts = [
                TaskDraft(
                    owner_agent=item.owner_agent,
                    task_type=item.task_type,
                    title=item.title,
                    description=item.description,
                    location=item.location,
                    priority=item.priority,
                    start_at=item.start_at,
                    due_at=item.due_at,
                    estimated_minutes=item.estimated_minutes,
                )
                for item in refreshed.tasks
            ]
            warnings = [item for item in (refreshed.conflict_summary or []) if item.startswith("工具提示：")]
            replace_plan_conflicts(session, refreshed, detect_conflicts(drafts) + warnings)
            text = plan_text(plan_rows(refreshed), "已按你的要求修改计划：")
            message = add_message(session, conversation_id, "assistant", text)
            return {"action": "updated", "plan": serialize_plan(refreshed), "message": {"content": message.content}}

    actionable, clarification = assess_plan_request(prompt)
    if not actionable:
        message = save_assistant(conversation_id, clarification)
        return {"action": "message", "message": message}
    time_question = schedule_clarification(prompt)
    if time_question:
        message = save_assistant(conversation_id, time_question)
        return {"action": "clarification", "pending_request": prompt, "message": message}

    job = job_manager.create("plan")
    asyncio.create_task(run_plan_job(job.id, prompt, conversation_id, draft.id if draft else None))
    return {"action": "job", "job_id": job.id, "kind": "plan"}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, after: int = 0, user_id: int = Depends(current_user)) -> StreamingResponse:
    del user_id
    if job_manager.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job 不存在或已过期")

    async def event_stream():
        async for event in job_manager.stream(job_id, after):
            yield f"event: {event.event}\ndata: {json.dumps(event.as_dict(), ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.patch("/api/tasks/{task_id}/result")
def update_task_result(task_id: int, payload: TaskResultRequest, user_id: int = Depends(current_user)) -> dict:
    del user_id
    with session_scope() as session:
        task = set_task_result(session, task_id, payload.completed, payload.reason)
        return serialize_task(task)


@app.post("/api/learning/{record_id}/quiz")
def submit_learning_quiz(record_id: int, payload: QuizSubmission, user_id: int = Depends(current_user)) -> dict:
    del user_id
    with session_scope() as session:
        record = submit_quiz(session, record_id, payload.answers)
        return {"score": record.score, "mastery": record.mastery_level, "task_status": record.task.status}


def process_feishu_message(event_row_id: int, open_id: str, text: str) -> None:
    try:
        if settings.feishu_owner_open_id and open_id != settings.feishu_owner_open_id:
            feishu_client.send_text(open_id, "当前机器人仅对已绑定用户开放。")
            return
        with session_scope() as session:
            conversation = get_or_create_conversation(session)
            conversation_id = conversation.id
            add_message(session, conversation_id, "user", text)
            state = get_channel_state(session, "feishu", open_id)
            pending = state.pending_request
            draft = latest_draft(session)

        if is_review_request(text):
            result = generate_review_sync(conversation_id, today_local())
            feishu_client.send_text(open_id, result["message"])
        elif draft and is_plan_confirmation(text):
            with session_scope() as session:
                plan = get_plan(session, draft.id)
                confirm_plan(session, plan.id)
                reply = encouraging_summary(plan_rows(plan))
                add_message(session, conversation_id, "assistant", reply)
            feishu_client.send_text(open_id, reply)
        else:
            request_text = f"{pending}\n补充信息：{text}" if pending else text
            actionable, clarification = assess_plan_request(request_text)
            if not actionable:
                reply = clarification
                with session_scope() as session:
                    add_message(session, conversation_id, "assistant", reply)
                feishu_client.send_text(open_id, reply)
            else:
                question = "" if pending else schedule_clarification(request_text)
                if question:
                    with session_scope() as session:
                        set_channel_pending_request(session, "feishu", open_id, text)
                        add_message(session, conversation_id, "assistant", question)
                    feishu_client.send_text(open_id, question)
                else:
                    result = generate_plan_sync(request_text, conversation_id, draft.id if draft else None)
                    with session_scope() as session:
                        set_channel_pending_request(session, "feishu", open_id, "")
                    plan = result["plan"]
                    lines = [f"{item['start_at'][11:16]}–{item['due_at'][11:16]} · {item['title']}" for item in plan["tasks"]]
                    feishu_client.send_plan_card(open_id, plan["id"], f"{plan['target_date']} 计划草稿", lines)
        with session_scope() as session:
            mark_channel_event_processed(session, event_row_id)
    except Exception:
        with session_scope() as session:
            mark_channel_event_processed(session, event_row_id, "FAILED")
        raise


@app.post("/api/feishu/events")
async def feishu_events(payload: dict, background_tasks: BackgroundTasks) -> dict:
    if payload.get("type") == "url_verification":
        if settings.feishu_verification_token and payload.get("token") != settings.feishu_verification_token:
            raise HTTPException(status_code=403, detail="invalid verification token")
        return {"challenge": payload.get("challenge", "")}
    header = payload.get("header", {})
    if settings.feishu_verification_token and header.get("token") != settings.feishu_verification_token:
        raise HTTPException(status_code=403, detail="invalid verification token")
    event = payload.get("event", {})
    message = event.get("message", {})
    sender = event.get("sender", {}).get("sender_id", {})
    event_id = header.get("event_id") or message.get("message_id")
    open_id = sender.get("open_id")
    if not event_id or not open_id:
        return {"code": 0}
    try:
        content = json.loads(message.get("content") or "{}")
    except json.JSONDecodeError:
        content = {}
    text = str(content.get("text", "")).strip()
    if not text:
        return {"code": 0}
    with session_scope() as session:
        row = record_channel_event(session, "feishu", event_id, header.get("event_type", ""), payload)
        if row is None:
            return {"code": 0}
        row_id = row.id
    background_tasks.add_task(process_feishu_message, row_id, open_id, text)
    return {"code": 0}


@app.post("/api/feishu/card-actions")
def feishu_card_actions(payload: dict) -> dict:
    token = payload.get("token") or payload.get("header", {}).get("token")
    if settings.feishu_verification_token and token != settings.feishu_verification_token:
        raise HTTPException(status_code=403, detail="invalid verification token")
    action = payload.get("action", {}).get("value", {})
    open_id = payload.get("open_id") or payload.get("operator", {}).get("open_id")
    if settings.feishu_owner_open_id and open_id != settings.feishu_owner_open_id:
        raise HTTPException(status_code=403, detail="user not allowed")
    if action.get("action") == "confirm_plan":
        with session_scope() as session:
            plan = get_plan(session, int(action["plan_id"]))
            confirm_plan(session, plan.id)
        return {"toast": {"type": "success", "content": "计划已确认"}}
    return {"toast": {"type": "info", "content": "操作已收到"}}


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
