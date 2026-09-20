from __future__ import annotations

import re
from datetime import datetime, timedelta


ACTION_WORDS = (
    "学习",
    "复习",
    "阅读",
    "完成",
    "完善",
    "开发",
    "实现",
    "处理",
    "制作",
    "编写",
    "测试",
    "修复",
    "整理",
    "搭建",
    "设计",
    "运动",
    "跑步",
    "健身",
    "锻炼",
    "出行",
    "提醒",
    "安排",
    "计划",
)


def assess_plan_request(text: str) -> tuple[bool, str]:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return False, "请告诉我今天想完成什么，例如任务内容、预计时长或截止时间。"
    if len(normalized) <= 1:
        return False, "我还无法从这一个字判断你的目标。请补充要完成的事情和期望时长。"
    if normalized.lower() in {"你好", "您好", "hi", "hello", "在吗", "嗯", "哦", "好的", "测试"}:
        return False, "你好！请告诉我今天具体想完成什么，我会帮你拆解和排期。"
    if not any(word in normalized for word in ACTION_WORDS):
        return False, "这段内容还不足以生成计划。你希望完成什么任务？可以同时告诉我时长或截止时间。"
    if normalized in {"学习", "阅读", "复习"}:
        return False, "你想学习什么主题？预计投入多长时间？"
    return True, ""


def is_plan_confirmation(text: str) -> bool:
    normalized = re.sub(r"[\s，。！!,.]", "", text or "").lower()
    return normalized in {"确认", "确认计划", "确认整份计划", "可以", "没问题", "按这个执行", "就这样", "开始执行"}


def plan_text(tasks: list[dict], heading: str = "我已经整理好计划草稿：") -> str:
    ordered = sorted(tasks, key=lambda item: item["start"])
    lines = [heading]
    for index, task in enumerate(ordered, 1):
        lines.append(
            f"{index}. {task['start']:%H:%M}–{task['due']:%H:%M}｜{task['title']}｜{task['minutes']} 分钟｜{task['priority']}"
        )
    total = sum(int(task["minutes"]) for task in ordered)
    lines.append(f"总计 {len(ordered)} 项、{total} 分钟。")
    lines.append("回复“确认计划”即可加入今日任务；也可以直接说，例如“把运动改成 1 小时”或“把第二项改到晚上 8 点”。")
    return "\n\n".join(lines)


def encouraging_summary(tasks: list[dict]) -> str:
    ordered = sorted(tasks, key=lambda item: item["start"])
    if not ordered:
        return "计划已经确认。今天稳稳向前一步就很好。"
    total = sum(int(task["minutes"]) for task in ordered)
    task_names = "、".join(task["title"] for task in ordered)
    return (
        f"计划确认成功！今天共安排 {len(ordered)} 项任务，预计投入 {total} 分钟：{task_names}。"
        f"第一项从 {ordered[0]['start']:%H:%M} 开始，最后一项预计在 {ordered[-1]['due']:%H:%M} 前完成。"
        "不需要追求一次做到完美，按顺序完成、及时更新状态，就是很扎实的进步。加油，今天也会是有收获的一天！"
    )


def parse_plan_change(text: str, tasks: list[dict]) -> tuple[int | None, dict, str]:
    """Parse common conversational edits without spending an LLM call."""
    if not tasks:
        return None, {}, "当前没有可修改的计划。"

    target: dict | None = None
    ordinal_match = re.search(r"第\s*([一二三四五六七八九十\d]+)\s*(?:个|项)", text)
    if ordinal_match:
        ordinal_text = ordinal_match.group(1)
        mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        position = int(ordinal_text) if ordinal_text.isdigit() else mapping.get(ordinal_text, 0)
        ordered = sorted(tasks, key=lambda item: item["start"])
        if 1 <= position <= len(ordered):
            target = ordered[position - 1]

    aliases = ("运动", "跑步", "健身", "学习", "资讯", "AI", "ai", "工作台", "回忆录", "阅读")
    if target is None:
        matches = [task for task in tasks if any(alias in text and alias.lower() in task["title"].lower() for alias in aliases)]
        if len(matches) == 1:
            target = matches[0]
    if target is None and len(tasks) == 1:
        target = tasks[0]
    if target is None:
        return None, {}, "请说明要修改哪一项，例如“把第二项改到晚上 8 点”或“把运动改成 1 小时”。"

    changes: dict = {}
    duration_match = re.search(r"(\d+(?:\.\d+)?)\s*(小时|分钟)", text)
    if duration_match:
        amount = float(duration_match.group(1))
        changes["estimated_minutes"] = round(amount * 60) if duration_match.group(2) == "小时" else round(amount)

    time_match = re.search(
        r"(?:改到|安排到|调整到|开始时间(?:改为|设为)?|从)\s*(晚上|下午|中午|上午|早上)?\s*(\d{1,2})(?:[:：](\d{2})|点(?:(\d{1,2})分?)?)",
        text,
    )
    if time_match:
        period, hour_text, minute_a, minute_b = time_match.groups()
        hour = int(hour_text)
        minute = int(minute_a or minute_b or 0)
        if period in {"晚上", "下午"} and hour < 12:
            hour += 12
        if period == "中午" and hour < 11:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            changes["start_time"] = datetime.min.replace(hour=hour, minute=minute).time()

    priority_match = re.search(r"(?:优先级)?(?:改为|调整为|设为)\s*(高|中|低)(?:优先级)?", text)
    if priority_match:
        changes["priority"] = {"高": "high", "中": "medium", "低": "low"}[priority_match.group(1)]

    title_match = re.search(r"(?:名称|标题)(?:改为|改成|设为)\s*[“\"]?([^”\"，。]+)", text)
    if title_match:
        changes["title"] = title_match.group(1).strip()

    if not changes:
        return target["id"], {}, "我找到了对应任务，但没有识别出要改的时间、时长、优先级或名称，请再具体一点。"

    duration = int(changes.get("estimated_minutes", target["minutes"]))
    start_at = datetime.combine(target["start"].date(), changes.get("start_time", target["start"].time()))
    changes["start_at"] = start_at
    changes["due_at"] = start_at + timedelta(minutes=duration)
    return target["id"], changes, ""
