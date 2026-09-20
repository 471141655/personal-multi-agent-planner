from __future__ import annotations

import os
from datetime import date, datetime

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
from app.conversation import assess_plan_request, encouraging_summary, is_plan_confirmation, parse_plan_change, plan_text
from app.database import init_db, session_scope
from app.repository import (
    add_message,
    build_review_facts,
    confirm_plan,
    dismiss_reminder,
    due_reminders,
    get_or_create_conversation,
    get_plan,
    latest_agent_runs,
    latest_draft,
    replace_plan_conflicts,
    recent_messages,
    review_for_day,
    save_generated_plan,
    set_task_result,
    snooze_reminder,
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


def render_reminders() -> None:
    with session_scope() as session:
        reminders = due_reminders(session)
        rendered = [(rem.id, rem.attempt_count, task.id, task.title, task.due_at) for rem, task in reminders]
    for reminder_id, attempt_count, task_id, title, due_at in rendered:
        st.warning(f"⏰ 任务已逾期：{title}（截止 {due_at:%H:%M}，第 {attempt_count}/3 次提醒）")
        a, b, c, d = st.columns(4)
        if a.button("标记完成", key=f"rem_done_{reminder_id}"):
            with session_scope() as session:
                set_task_result(session, task_id, True)
                dismiss_reminder(session, reminder_id)
            st.rerun()
        if b.button("15 分钟后", key=f"rem_15_{reminder_id}"):
            with session_scope() as session:
                snooze_reminder(session, reminder_id, 15)
            st.rerun()
        if c.button("20 分钟后", key=f"rem_20_{reminder_id}"):
            with session_scope() as session:
                snooze_reminder(session, reminder_id, 20)
            st.rerun()
        if d.button("忽略本次", key=f"rem_ignore_{reminder_id}"):
            with session_scope() as session:
                dismiss_reminder(session, reminder_id)
            st.rerun()


try:
    fragment = st.fragment(run_every="30s")
    fragment(render_reminders)()
except TypeError:
    render_reminders()


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
m4.metric("默认城市", "北京")


left, center, right = st.columns([1.05, 2.0, 1.15], gap="large")


with left:
    st.subheader("今日任务")
    with session_scope() as session:
        tasks = tasks_for_day(session, today)
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
            for task in tasks
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
    with session_scope() as session:
        today_tasks = tasks_for_day(session, today)
        learning_rows = []
        for task in today_tasks:
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

    st.subheader("Agent 状态")
    with session_scope() as session:
        runs = latest_agent_runs(session)
        run_rows = [(run.agent_name, run.status, run.duration_ms, run.retry_count, run.error_code) for run in runs]
    if not run_rows:
        st.caption("暂无 Agent 调用记录。")
    for name, status, duration, retries, error in run_rows:
        icon = "✅" if status == "SUCCEEDED" else "⚠️"
        st.markdown(f"{icon} **{name}** · {duration} ms · 重试 {retries}")
        if error:
            st.caption(error)

    st.markdown("#### 执行阶段")
    agent_progress_slot = st.empty()

    def render_agent_trace() -> None:
        trace = st.session_state.get("agent_trace", [])
        if not trace:
            agent_progress_slot.caption("生成计划时，这里会实时显示执行阶段。")
            return
        lines = [f"{index + 1}. **{item['label']}** · {item['message']}" for index, item in enumerate(trace)]
        agent_progress_slot.markdown("\n\n".join(lines))

    render_agent_trace()


with center:
    st.subheader("AI 对话与计划")
    st.caption("示例：今天下班后，我想学习了解 AI 最新资讯，还想运动一个小时。")
    with session_scope() as session:
        conversation = get_or_create_conversation(session)
        conversation_id = conversation.id
        history = [(message.role, message.content, message.created_at) for message in recent_messages(session, conversation_id, limit=50)]
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
            else:
                task_id, changes, clarification = parse_plan_change(prompt, draft_data["tasks"])
                if not changes:
                    st.session_state["agent_trace"] = [{"label": "Leader", "message": "识别为计划修改，但信息不足，未调用子 Agent"}]
                    render_agent_trace()
                    save_assistant_message(clarification)
                else:
                    with session_scope() as session:
                        update_draft_task(session, task_id, changes)
                        refreshed = latest_draft(session)
                        drafts = [TaskDraft(owner_agent=item.owner_agent, task_type=item.task_type, title=item.title, description=item.description, location=item.location, priority=item.priority, start_at=item.start_at, due_at=item.due_at, estimated_minutes=item.estimated_minutes) for item in refreshed.tasks]
                        warnings = [item for item in (refreshed.conflict_summary or []) if item.startswith("工具提示：")]
                        replace_plan_conflicts(session, refreshed, detect_conflicts(drafts) + warnings)
                        revised_rows = plan_rows(refreshed)
                        assistant_text = plan_text(revised_rows, "已按你的要求修改计划：")
                        add_message(session, conversation_id, "assistant", assistant_text)
                    st.session_state["agent_trace"] = [{"label": "Leader", "message": "已在本地完成计划修改，未重复调用资讯与天气工具"}]
                    render_agent_trace()
                    st.rerun()
        else:
            actionable, clarification = assess_plan_request(prompt)
            if not actionable:
                st.session_state["agent_trace"] = [{"label": "Leader", "message": "输入信息不足，已停止路由并向用户追问"}]
                render_agent_trace()
                save_assistant_message(clarification)
            else:
                st.session_state["agent_trace"] = []
                with st.spinner("Agent 团队正在生成计划……", show_time=True):
                    def show_agent_progress(agent: str, message: str) -> None:
                        labels = {"leader": "Leader", "learning": "Learning Agent", "life": "Life Agent", "scheduler": "排期与冲突检查"}
                        st.session_state["agent_trace"].append({"label": labels.get(agent, agent), "message": message})
                        render_agent_trace()

                    generated = PlannerOrchestrator().generate(prompt, progress=show_agent_progress)
                with st.spinner("正在保存计划草稿……"):
                    with session_scope() as session:
                        saved_plan = save_generated_plan(session, generated)
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


st.divider()
st.subheader("今日复盘")
if st.button("生成今日复盘", type="primary"):
    with st.status("Review Agent 正在生成今日复盘……", expanded=True) as review_status:
        review_status.write("正在读取今日任务与完成状态")
        with session_scope() as session:
            review_tasks = tasks_for_day(session, today)
            facts = build_review_facts(review_tasks)
        review_status.write("正在分析完成率、未完成原因和学习结果")
        output = PlannerOrchestrator().review(facts)
        review_status.write("正在保存复盘与明日建议")
        with session_scope() as session:
            upsert_review(session, today, output, facts)
        review_status.update(label="今日复盘已生成", state="complete", expanded=False)

with session_scope() as session:
    review = review_for_day(session, today)
    if review:
        review_data = {"summary": review.summary, **(review.details_json or {})}
    else:
        review_data = None
if review_data:
    st.write(review_data["summary"])
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**做得好的地方**")
        for item in review_data.get("wins", []):
            st.write(f"- {item}")
    with c2:
        st.markdown("**主要问题**")
        for item in review_data.get("issues", []):
            st.write(f"- {item}")
    with c3:
        st.markdown("**明日建议**")
        for item in review_data.get("suggestions", []):
            st.write(f"- {item}")
