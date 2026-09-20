from __future__ import annotations

import os
from datetime import datetime

import streamlit as st


try:
    cloud_secrets = dict(st.secrets)
except Exception:
    cloud_secrets = {}
for key in ["DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DATABASE_URL", "APP_PASSWORD", "APP_PASSWORD_HASH", "APP_TIMEZONE"]:
    if key in cloud_secrets and not os.getenv(key):
        os.environ[key] = str(cloud_secrets[key])

from app.agents import PlannerOrchestrator, detect_conflicts
from app.auth import verify_password
from app.conversation import assess_plan_request, encouraging_summary, is_new_plan_request, is_plan_confirmation, parse_plan_change, plan_text
from app.database import init_db, session_scope
from app.repository import (
    add_message,
    auto_fail_overdue_tasks,
    build_review_facts,
    confirm_plan,
    expire_stale_drafts,
    get_or_create_conversation,
    get_plan,
    latest_draft,
    replace_plan_conflicts,
    recent_messages,
    save_generated_plan,
    set_task_result,
    supersede_plan,
    submit_quiz,
    tasks_for_day,
    update_draft_task,
    upsert_review,
)
from app.schemas import TaskDraft
from app.timeutils import today_local


st.set_page_config(page_title="生活学习 Agent 工作台", page_icon="🧭", layout="wide", initial_sidebar_state="collapsed")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1600px;}
    [data-testid="stMetric"] {background: #f7f8fc; border: 1px solid #e8eaf2; padding: .7rem; border-radius: .8rem;}
    .agent-chip {display:inline-block; padding:.18rem .55rem; border-radius:999px; background:#eef2ff; margin-right:.3rem; font-size:.78rem;}
    .task-card {border:1px solid #e6e8ef; border-radius:12px; padding:12px; margin-bottom:10px; background:white;}
    .agent-hud {height:94px; display:flex; align-items:center; gap:.75rem; padding:.65rem .85rem; border-radius:14px; color:#eaf6ff; background:linear-gradient(135deg,#111827,#172554); border:1px solid #334155; overflow:hidden;}
    .agent-avatar {width:58px; height:58px; flex:0 0 58px; border-radius:50%; background:#0f172a; border:2px solid #38bdf8; padding:7px; box-shadow:0 0 14px rgba(56,189,248,.35); animation:agentPulse 1.4s ease-in-out infinite;}
    .agent-avatar svg {width:100%; height:100%; stroke:#7dd3fc; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round;}
    .agent-hud-title {font-size:.78rem; letter-spacing:.08em; color:#7dd3fc; font-weight:700;}
    .agent-hud-message {font-size:.86rem; margin-top:.18rem; line-height:1.25;}
    .mission-complete {color:#86efac; font-weight:800; letter-spacing:.08em;}
    @keyframes agentPulse {50% {box-shadow:0 0 24px rgba(56,189,248,.7); transform:scale(1.025);}}
    @media (max-width: 768px) {
      .block-container {padding-left: .8rem; padding-right: .8rem;}
      div[data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
      div[data-testid="column"] {min-width: 100% !important; width: 100% !important; flex: 1 1 100% !important;}
      .stButton button {min-height: 44px; width:100%;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def bootstrap() -> bool:
    init_db()
    return True


bootstrap()


def login() -> None:
    st.title("🧭 个人学习生活工作台")
    st.caption("单用户 V0.1 · 输入密码进入")
    with st.form("login"):
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("登录", use_container_width=True)
    if submitted:
        if verify_password(password):
            st.session_state.authenticated = True
            st.rerun()
        st.error("密码错误")


if not st.session_state.get("authenticated"):
    login()
    st.stop()


def set_flash(message: str, level: str = "success") -> None:
    st.session_state["flash_message"] = (level, message)


def update_task_result_callback(task_id: int, completed: bool, reason_key: str | None = None) -> None:
    try:
        reason = st.session_state.get(reason_key) if reason_key else None
        with session_scope() as session:
            set_task_result(session, task_id, completed, reason)
        set_flash("任务状态已更新。")
    except Exception as exc:
        set_flash(f"更新失败：{exc}", "error")


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


def confirm_plan_in_chat_callback(plan_id: int, conversation_id: int) -> None:
    try:
        with session_scope() as session:
            plan = get_plan(session, plan_id)
            if not plan:
                raise ValueError("计划不存在")
            rows = plan_rows(plan)
            confirm_plan(session, plan_id)
            add_message(session, conversation_id, "assistant", encouraging_summary(rows))
        set_flash("计划已确认，今日任务已经生成。")
    except Exception as exc:
        set_flash(f"确认失败：{exc}", "error")


def submit_quiz_callback(record_id: int, question_count: int) -> None:
    answers = [st.session_state.get(f"q_{record_id}_{index}") for index in range(question_count)]
    if any(answer is None for answer in answers):
        st.session_state[f"quiz_error_{record_id}"] = "请完成全部题目。"
        return
    try:
        with session_scope() as session:
            submit_quiz(session, record_id, [int(answer) for answer in answers])
        st.session_state.pop(f"quiz_error_{record_id}", None)
        set_flash("自测已提交并自动判分。")
    except Exception as exc:
        st.session_state[f"quiz_error_{record_id}"] = f"提交失败：{exc}"


AGENT_AVATARS = {
    "leader": """<svg viewBox="0 0 48 48"><circle cx="24" cy="18" r="9"/><path d="M9 43c2-10 8-15 15-15s13 5 15 15M24 5v4M10 18H6m36 0h-4M13 8l3 3m19-3-3 3"/></svg>""",
    "learning": """<svg viewBox="0 0 48 48"><path d="M7 10c7-2 12 0 17 4v28c-5-4-10-6-17-4V10Zm34 0c-7-2-12 0-17 4v28c5-4 10-6 17-4V10ZM12 17h7m-7 6h7m10-6h7m-7 6h7"/></svg>""",
    "life": """<svg viewBox="0 0 48 48"><path d="M24 42V20M24 31c-8 0-14-5-15-13 8-1 14 3 15 10m0-2c1-8 7-13 15-12 0 8-6 14-15 14"/><circle cx="24" cy="9" r="4"/></svg>""",
    "review": """<svg viewBox="0 0 48 48"><rect x="9" y="8" width="30" height="35" rx="4"/><path d="M18 7V4h12v3M16 20l4 4 8-9m-12 19h16"/></svg>""",
}


@st.fragment(run_every="30s")
def overdue_watcher(conversation_id: int) -> None:
    """Quietly move overdue tasks to chat instead of rendering page banners."""
    with session_scope() as session:
        overdue = auto_fail_overdue_tasks(session)
        for task in overdue:
            add_message(
                session,
                conversation_id,
                "assistant",
                f"⏰ Life Agent 提醒：任务“{task.title}”已超过截止时间，系统已自动标记为未完成（原因：超过截止时间未完成）。",
            )
    if overdue:
        st.rerun()


st.title("🧭 今日智能工作台")
flash = st.session_state.pop("flash_message", None)
if flash:
    level, message = flash
    (st.error if level == "error" else st.success)(message)
today = today_local()
with session_scope() as session:
    initial_tasks = tasks_for_day(session, today)
done_count = sum(task.status == "COMPLETED" for task in initial_tasks)
m1, m2, m3, m4 = st.columns(4)
m1.metric("今日任务", len(initial_tasks))
m2.metric("已完成", done_count)
m3.metric("完成率", f"{round(done_count / len(initial_tasks) * 100) if initial_tasks else 0}%")
with m4:
    agent_hud_slot = st.empty()


def render_agent_hud(agent: str | None = None, message: str = "") -> None:
    if agent is None:
        avatar = AGENT_AVATARS["leader"]
        title = "MISSION COMPLETE"
        detail = "Agent 团队已就绪"
        title_class = "mission-complete"
    else:
        labels = {"leader": "LEADER", "learning": "LEARNING AGENT", "life": "LIFE AGENT", "review": "REVIEW AGENT"}
        avatar = AGENT_AVATARS.get(agent, AGENT_AVATARS["leader"])
        title = labels.get(agent, agent.upper())
        detail = message or "正在执行任务……"
        title_class = "agent-hud-title"
    agent_hud_slot.markdown(
        f'<div class="agent-hud"><div class="agent-avatar">{avatar}</div>'
        f'<div><div class="{title_class}">{title}</div><div class="agent-hud-message">{detail}</div></div></div>',
        unsafe_allow_html=True,
    )


render_agent_hud()


left, center, right = st.columns([1.05, 2.0, 1.15], gap="large")


with left:
    st.subheader("今日任务")
    task_rows = [
        {
            "id": task.id,
            "title": task.title,
            "type": task.task_type,
            "priority": task.priority,
            "start": task.start_at,
            "due": task.due_at,
            "status": task.status,
            "reason": task.not_completed_reason,
        }
        for task in initial_tasks
    ]
    if not task_rows:
        st.info("还没有已确认的今日任务。")
    for task in task_rows:
        with st.container(border=True):
            st.markdown(f"**{task['title']}**")
            st.caption(f"{task['start']:%H:%M}–{task['due']:%H:%M} · {task['priority']} · {task['status']}")
            if task["status"] not in ["COMPLETED", "NOT_COMPLETED", "CANCELLED"]:
                reason_key = f"reason_{task['id']}"
                st.button("✓ 已完成", key=f"done_{task['id']}", use_container_width=True, on_click=update_task_result_callback, args=(task["id"], True))
                st.selectbox("未完成原因", ["时间不足", "临时事务", "计划不合理", "身体状态", "缺乏动力", "任务过难", "其他"], key=reason_key)
                st.button("标记未完成", key=f"miss_{task['id']}", use_container_width=True, on_click=update_task_result_callback, args=(task["id"], False, reason_key))
            elif task["reason"]:
                st.caption(f"原因：{task['reason']}")


with right:
    st.subheader("学习进度")
    learning_rows = []
    for task in initial_tasks:
        if task.learning_record:
            record = task.learning_record
            learning_rows.append({"task_id": task.id, "title": task.title, "record_id": record.id, "goal": record.learning_goal, "quiz": list(record.quiz_json or []), "score": record.score, "mastery": record.mastery_level})
    if not learning_rows:
        st.caption("确认学习计划后，这里会显示自测题。")
    for learning in learning_rows:
        with st.container(border=True):
            st.markdown(f"**{learning['title']}**")
            st.caption(learning["goal"])
            if learning["score"] is not None:
                st.metric("自测成绩", f"{learning['score']}/3")
                st.success(learning["mastery"])
            else:
                with st.form(f"quiz_{learning['record_id']}"):
                    for index, question in enumerate(learning["quiz"]):
                        st.radio(f"{index + 1}. {question['question']}", list(range(4)), format_func=lambda value, opts=question["options"]: opts[value], index=None, key=f"q_{learning['record_id']}_{index}")
                    st.form_submit_button(
                        "提交自测",
                        use_container_width=True,
                        on_click=submit_quiz_callback,
                        args=(learning["record_id"], len(learning["quiz"])),
                    )
                quiz_error = st.session_state.get(f"quiz_error_{learning['record_id']}")
                if quiz_error:
                    st.error(quiz_error)

with center:
    st.subheader("AI 对话与计划")
    st.caption("示例：今天下班后，我想学习了解 AI 最新资讯，还想运动一个小时。")
    with session_scope() as session:
        conversation = get_or_create_conversation(session)
        conversation_id = conversation.id
    overdue_watcher(conversation_id)
    with session_scope() as session:
        history = [(message.role, message.content, message.created_at) for message in recent_messages(session, conversation_id, limit=50)]
        expire_stale_drafts(session, today)
        draft = latest_draft(session)
        draft_data = (
            {"id": draft.id, "conflicts": list(draft.conflict_summary or []), "tasks": plan_rows(draft)}
            if draft
            else None
        )
    chat_window = st.container(height=360, border=True)
    with chat_window:
        if not history:
            st.caption("对话记录会固定显示在这里，可使用鼠标滚轮查看上下文。")
        for role, content, created_at in history:
            with st.chat_message(role if role in ["user", "assistant"] else "assistant"):
                st.write(content)
                st.caption(created_at.strftime("%Y-%m-%d %H:%M"))
        if draft_data:
            blocking = [item for item in draft_data["conflicts"] if not item.startswith("工具提示：")]
            st.caption("当前计划正在等待你的确认或修改。")
            st.button(
                "确认计划并生成今日任务",
                type="primary",
                disabled=bool(blocking),
                key=f"chat_confirm_{draft_data['id']}",
                on_click=confirm_plan_in_chat_callback,
                args=(draft_data["id"], conversation_id),
                use_container_width=True,
            )
        if st.button("📝 生成今日复盘", key="chat_review", use_container_width=True):
            st.session_state["review_requested"] = True

    def show_chat_message(role: str, content: str, created_at: datetime) -> None:
        with chat_window:
            with st.chat_message(role):
                st.write(content)
                st.caption(created_at.strftime("%Y-%m-%d %H:%M"))

    def save_assistant_message(content: str):
        with session_scope() as session:
            message = add_message(session, conversation_id, "assistant", content)
        show_chat_message("assistant", content, message.created_at)
        return message

    def generate_new_plan(request_text: str, initial_trace: list[dict] | None = None) -> None:
        if initial_trace:
            render_agent_hud("leader", initial_trace[-1]["message"])
        with st.spinner("Agent 团队正在生成新计划……", show_time=True):
            def show_agent_progress(agent: str, message: str) -> None:
                hud_agent = "leader" if agent == "scheduler" else agent
                render_agent_hud(hud_agent, message)

            generated = PlannerOrchestrator().generate(request_text, progress=show_agent_progress)
        with st.spinner("正在保存新计划草稿……"):
            with session_scope() as session:
                saved_plan = save_generated_plan(session, generated, input_summary=request_text)
                generated_rows = plan_rows(saved_plan)
                assistant_text = plan_text(generated_rows)
                if generated.conflicts:
                    assistant_text += "\n\n提示：\n" + "\n".join(f"- {item}" for item in generated.conflicts)
                assistant_message = add_message(session, conversation_id, "assistant", assistant_text)
        show_chat_message("assistant", assistant_text, assistant_message.created_at)
        blocking = [item for item in generated.conflicts if not item.startswith("工具提示：")]
        with chat_window:
            st.button(
                "确认计划并生成今日任务",
                type="primary",
                disabled=bool(blocking),
                key=f"chat_confirm_new_{saved_plan.id}",
                on_click=confirm_plan_in_chat_callback,
                args=(saved_plan.id, conversation_id),
                use_container_width=True,
            )
        render_agent_hud()

    if st.session_state.pop("review_requested", False):
        render_agent_hud("review", "正在读取今日任务与完成情况")
        with st.spinner("Review Agent 正在生成今日复盘……", show_time=True):
            with session_scope() as session:
                facts = build_review_facts(tasks_for_day(session, today))
            render_agent_hud("review", "正在分析完成率、未完成原因和学习结果")
            output = PlannerOrchestrator().review(facts)
            review_text = (
                f"📝 Review Agent · 今日复盘\n\n{output.summary}\n\n"
                + "**做得好的地方**\n"
                + "\n".join(f"- {item}" for item in output.wins)
                + "\n\n**主要问题**\n"
                + "\n".join(f"- {item}" for item in output.issues)
                + "\n\n**明日建议**\n"
                + "\n".join(f"- {item}" for item in output.suggestions)
            )
            with session_scope() as session:
                upsert_review(session, today, output, facts)
                review_message = add_message(session, conversation_id, "assistant", review_text)
        show_chat_message("assistant", review_text, review_message.created_at)
        render_agent_hud()

    prompt = st.chat_input("告诉系统你今天想完成什么……")
    if prompt:
        with session_scope() as session:
            user_message = add_message(session, conversation_id, "user", prompt)
        show_chat_message("user", prompt, user_message.created_at)

        if draft_data:
            blocking = [item for item in draft_data["conflicts"] if not item.startswith("工具提示：")]
            if is_plan_confirmation(prompt):
                if blocking:
                    save_assistant_message("当前计划仍有时间冲突，请先告诉我如何调整：\n\n" + "\n".join(f"- {item}" for item in blocking))
                else:
                    with session_scope() as session:
                        plan = get_plan(session, draft_data["id"])
                        rows = plan_rows(plan)
                        confirm_plan(session, draft_data["id"])
                        add_message(session, conversation_id, "assistant", encouraging_summary(rows))
                    st.rerun()
            elif is_new_plan_request(prompt):
                with session_scope() as session:
                    supersede_plan(session, draft_data["id"])
                    add_message(session, conversation_id, "assistant", "识别到这是新的计划请求，旧的未确认草稿已停止，正在为你重新规划。")
                generate_new_plan(prompt, [{"label": "Leader", "message": f"新计划请求已替代旧草稿 #{draft_data['id']}"}])
            else:
                task_id, changes, clarification = parse_plan_change(prompt, draft_data["tasks"])
                if not changes:
                    render_agent_hud("leader", "修改信息不足，正在请你补充")
                    save_assistant_message(clarification)
                    render_agent_hud()
                else:
                    render_agent_hud("leader", "正在修改计划并重新检查冲突")
                    with session_scope() as session:
                        update_draft_task(session, task_id, changes)
                        refreshed = latest_draft(session)
                        drafts = [TaskDraft(owner_agent=item.owner_agent, task_type=item.task_type, title=item.title, description=item.description, location=item.location, priority=item.priority, start_at=item.start_at, due_at=item.due_at, estimated_minutes=item.estimated_minutes) for item in refreshed.tasks]
                        warnings = [item for item in (refreshed.conflict_summary or []) if item.startswith("工具提示：")]
                        replace_plan_conflicts(session, refreshed, detect_conflicts(drafts) + warnings)
                        revised_rows = plan_rows(refreshed)
                        assistant_text = plan_text(revised_rows, "已按你的要求修改计划：")
                        add_message(session, conversation_id, "assistant", assistant_text)
                    st.rerun()
        else:
            actionable, clarification = assess_plan_request(prompt)
            if not actionable:
                render_agent_hud("leader", "输入信息不足，正在向你追问")
                save_assistant_message(clarification)
                render_agent_hud()
            else:
                generate_new_plan(prompt)
