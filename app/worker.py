from __future__ import annotations

import time
from datetime import datetime

from app.config import get_settings
from app.database import init_db, session_scope
from app.feishu import feishu_client
from app.repository import (
    add_message,
    auto_fail_overdue_tasks,
    enqueue_notification,
    ensure_daily_review_prompt,
    get_or_create_conversation,
    mark_notification_failed,
    mark_notification_sent,
    pending_notifications,
)
from app.timeutils import now_local, today_local


def run_once() -> dict:
    settings = get_settings()
    now = now_local()
    overdue_count = 0
    review_prompted = False

    with session_scope() as session:
        conversation = get_or_create_conversation(session)
        overdue = auto_fail_overdue_tasks(session, now)
        overdue_count = len(overdue)
        for task in overdue:
            text = f"⏰ Life Agent 提醒：任务“{task.title}”已超过截止时间，系统已自动标记为未完成。"
            add_message(session, conversation.id, "assistant", text)
            if settings.feishu_owner_open_id:
                enqueue_notification(
                    session,
                    "feishu",
                    settings.feishu_owner_open_id,
                    "TASK_OVERDUE",
                    f"task:{task.id}",
                    {"text": text},
                )

        review_hour, review_minute = (int(part) for part in settings.review_reminder_time.split(":", 1))
        if now.time() >= datetime.min.replace(hour=review_hour, minute=review_minute).time():
            prompt = ensure_daily_review_prompt(session, conversation.id, today_local())
            review_prompted = prompt is not None
            if prompt and settings.feishu_owner_open_id:
                enqueue_notification(
                    session,
                    "feishu",
                    settings.feishu_owner_open_id,
                    "DAILY_REVIEW_PROMPT",
                    f"review:{today_local().isoformat()}",
                    {"text": prompt.content},
                )

        queued = [
            {"id": item.id, "channel": item.channel, "recipient": item.recipient, "payload": dict(item.payload_json or {})}
            for item in pending_notifications(session, now)
        ]

    sent = 0
    failed = 0
    for item in queued:
        try:
            if item["channel"] != "feishu":
                raise RuntimeError(f"不支持的通知渠道：{item['channel']}")
            feishu_client.send_text(item["recipient"], item["payload"].get("text", ""))
            with session_scope() as session:
                mark_notification_sent(session, item["id"])
            sent += 1
        except Exception as exc:
            with session_scope() as session:
                mark_notification_failed(session, item["id"], str(exc))
            failed += 1

    return {"overdue": overdue_count, "review_prompted": review_prompted, "sent": sent, "failed": failed}


def main() -> None:
    init_db()
    settings = get_settings()
    while True:
        try:
            run_once()
        except Exception as exc:
            print(f"worker cycle failed: {exc}", flush=True)
        time.sleep(max(5, settings.worker_poll_seconds))


if __name__ == "__main__":
    main()
