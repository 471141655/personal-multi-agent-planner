from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta
from typing import Callable

from app.llm import DeepSeekClient, ModelUnavailable
from app.schemas import (
    GeneratedPlan,
    LearningOutput,
    LifeOutput,
    NewsItem,
    QuizQuestion,
    ReviewOutput,
    RouteDecision,
    TaskDraft,
)
from app.services.news import fetch_ai_news
from app.services.weather import fetch_weather
from app.timeutils import now_local, today_local


KNOWN_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "天津", "重庆", "苏州"]
ProgressCallback = Callable[[str, str], None]


def _today() -> date:
    return today_local()


def _at(target_date: date, hhmm: str) -> datetime:
    parsed = datetime.strptime(hhmm, "%H:%M").time()
    return datetime.combine(target_date, parsed)


def _fallback_route(user_input: str) -> RouteDecision:
    intents = []
    if any(word in user_input for word in ["学", "资讯", "阅读", "知识", "复习"]):
        intents.append("learning")
    if any(word in user_input for word in ["运动", "跑步", "健身", "散步", "作息", "睡觉"]):
        intents.append("life")
    if not intents:
        intents.append("task")
    city = next((candidate for candidate in KNOWN_CITIES if candidate in user_input), "北京")
    target_date = _today()
    if "后天" in user_input:
        target_date += timedelta(days=2)
    elif "明天" in user_input or "明晚" in user_input:
        target_date += timedelta(days=1)
    return RouteDecision(intents=intents, location=city, target_date=target_date.isoformat(), rationale="关键词安全路由")


def _fallback_learning(news: list[NewsItem]) -> LearningOutput:
    titles = "；".join(item.title for item in news[:3]) or "当前官方来源暂未返回最近资讯"
    summary = f"本次学习聚焦官方来源的近期动态：{titles}。请打开来源链接阅读原文，并比较各项更新的目标、能力与实际影响。"
    return LearningOutput(
        task_title="学习 AI 最新资讯",
        learning_goal="了解最近 7 天主要 AI 官方动态，并能复述至少 3 个关键变化。",
        material_summary=summary,
        completion_criteria="阅读摘要和原文，完成 3 道自测题。",
        suggested_start="20:30",
        duration_minutes=60,
        quiz=[
            QuizQuestion(question="本次资讯筛选的时间范围是？", options=["最近 24 小时", "最近 7 天", "最近 30 天", "不限时间"], correct_index=1, explanation="V0.1 默认筛选最近 7 天的官方资讯。"),
            QuizQuestion(question="判断资讯是否为实时内容最重要的依据是？", options=["模型语气", "标题长度", "来源链接与发布时间", "摘要字数"], correct_index=2, explanation="来源与发布时间是验证实时性的关键依据。"),
            QuizQuestion(question="当所有资讯源失败时，系统应如何处理？", options=["编造新闻", "使用旧知识冒充", "明确提示获取失败", "自动标记学习完成"], correct_index=2, explanation="系统必须显式降级，不能虚构实时信息。"),
        ],
    )


def _fallback_life(weather: dict, duration_minutes: int = 60) -> LifeOutput:
    rain = int(weather.get("precipitation_probability", 0) or 0)
    indoor = rain >= 50
    warmup = min(10, max(5, duration_minutes // 10))
    cooldown = warmup
    main = max(10, duration_minutes - warmup - cooldown)
    return LifeOutput(
        task_title=f"完成 {duration_minutes // 60} 小时运动" if duration_minutes % 60 == 0 else f"完成 {duration_minutes} 分钟运动",
        plan=f"完成热身 {warmup} 分钟、主体训练 {main} 分钟和拉伸 {cooldown} 分钟。",
        weather_advice=(f"{weather.get('city', '北京')} {weather.get('condition', '天气未知')}，降水概率 {rain}%。" + ("建议室内运动。" if indoor else "可以考虑户外运动。")),
        suggested_start="19:00",
        duration_minutes=duration_minutes,
        indoor_alternative=f"室内徒手训练、跑步机或瑜伽 {duration_minutes} 分钟。",
    )


def _duration_from_text(text: str, default: int = 60) -> int:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(小时|分钟)", text)
    if not match:
        return default
    value = float(match.group(1))
    minutes = round(value * 60) if match.group(2) == "小时" else round(value)
    return max(5, min(720, minutes))


def _requested_exercise_minutes(user_input: str) -> int:
    match = re.search(r"(?:运动|跑步|健身|锻炼)[^，。；,;]{0,12}?(\d+(?:\.\d+)?)\s*(小时|分钟)", user_input, re.IGNORECASE)
    if not match:
        return 60
    return _duration_from_text(match.group(0), 60)


def _clean_task_title(clause: str) -> str:
    title = clause.strip(" \t\r\n，。；,;")
    title = re.sub(
        r"^(?:我)?(?:今天|明天|后天|今晚|明晚|周末)?"
        r"(?:在家|在公司|在办公室)?(?:我)?"
        r"(?:打算|计划|想要|想|要|准备|需要)?(?:先|再|然后)?\s*",
        "",
        title,
    )
    return title.strip()[:120]


def _extract_general_tasks(user_input: str, target_date: date, location: str) -> list[TaskDraft]:
    """Keep explicit work/product tasks even when the model route falls back."""
    clauses = re.split(r"[，。；,;]+|(?:还有|还想|以及|并且|同时)", user_input)
    action_words = (
        "完善", "优化", "开发", "实现", "完成", "处理", "制作", "编写", "测试", "修复", "整理", "搭建", "设计",
        "找朋友", "见朋友", "约朋友", "吃饭", "聚餐", "拜访", "购物", "采购", "办事",
    )
    tasks: list[TaskDraft] = []
    seen: set[str] = set()
    for clause in clauses:
        normalized = clause.strip()
        if not normalized or not any(word in normalized for word in action_words):
            continue
        if any(word in normalized for word in ("学习", "资讯", "阅读", "运动", "跑步", "健身", "锻炼")):
            continue
        title = _clean_task_title(normalized)
        if not title or title in seen:
            continue
        seen.add(title)
        is_social = any(word in normalized for word in ("找朋友", "见朋友", "约朋友", "吃饭", "聚餐", "拜访"))
        duration = _duration_from_text(normalized, 120 if is_social else 60)
        placeholder = _at(target_date, "12:00" if is_social else "09:00")
        tasks.append(
            TaskDraft(
                owner_agent="leader",
                task_type="task",
                title=title,
                description="根据用户原始输入保留的任务；确认前可调整名称、时间和时长。",
                location=location,
                priority="medium" if is_social else "high",
                start_at=placeholder,
                due_at=placeholder + timedelta(minutes=duration),
                estimated_minutes=duration,
            )
        )
    return tasks


def _round_up_quarter(value: datetime) -> datetime:
    value = value.replace(second=0, microsecond=0)
    remainder = value.minute % 15
    return value if remainder == 0 else value + timedelta(minutes=15 - remainder)


def _explicit_plan_start(user_input: str, target_date: date) -> datetime | None:
    match = re.search(
        r"(?:从|可以从|可从|补充信息：)?\s*(早上|上午|中午|下午|晚上)?\s*"
        r"(\d{1,2})(?:[:：](\d{2})|点(?:(\d{1,2})分?)?)\s*(?:开始|以后|之后)",
        user_input,
    )
    if not match:
        return None
    period, hour_text, minute_a, minute_b = match.groups()
    hour = int(hour_text)
    minute = int(minute_a or minute_b or 0)
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return datetime.combine(target_date, dt_time(hour, minute))


def _schedule_tasks(tasks: list[TaskDraft], target_date: date, user_input: str) -> list[TaskDraft]:
    is_free_day = target_date.weekday() >= 5 or "周末" in user_input or any(marker in user_input for marker in ("在家", "休息", "请假", "全天", "随时"))
    explicit_start = _explicit_plan_start(user_input, target_date)
    base = explicit_start or _at(target_date, "09:00" if is_free_day else "18:45")
    if target_date == _today():
        base = max(base, _round_up_quarter(now_local() + timedelta(minutes=15)))
    priority_order = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(enumerate(tasks), key=lambda item: (priority_order[item[1].priority], item[0]))
    scheduled: list[TaskDraft] = []
    cursor = base
    for _, task in ordered:
        is_social_task = any(word in task.title for word in ("找朋友", "见朋友", "约朋友", "吃饭", "聚餐", "拜访"))
        preferred_start = task.start_at if is_social_task else cursor
        start = max(cursor, preferred_start)
        due = start + timedelta(minutes=task.estimated_minutes)
        scheduled.append(task.model_copy(update={"start_at": start, "due_at": due}))
        cursor = due + timedelta(minutes=15)
    return scheduled


class PlannerOrchestrator:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()

    def _call(self, name: str, schema, system: str, user: str, fallback, runs: list[dict], progress: ProgressCallback | None = None):
        started = time.perf_counter()
        try:
            result, retries = self.client.structured(schema, system, user)
            runs.append({"agent_name": name, "status": "SUCCEEDED", "retry_count": retries, "duration_ms": int((time.perf_counter() - started) * 1000), "output_json": result.model_dump(mode="json")})
            if progress:
                progress(name, "结构化输出已通过校验")
            return result
        except ModelUnavailable as exc:
            result = fallback()
            runs.append({"agent_name": name, "status": "FAILED", "retry_count": 1, "duration_ms": int((time.perf_counter() - started) * 1000), "error_code": str(exc)[:100], "output_json": result.model_dump(mode="json")})
            if progress:
                progress(name, "模型暂不可用，已切换本地可靠规则")
            return result

    def generate(self, user_input: str, progress: ProgressCallback | None = None) -> GeneratedPlan:
        request_id = uuid.uuid4().hex
        runs: list[dict] = []
        if progress:
            progress("leader", "正在识别日期、地点和全部任务要求")
        route = self._call(
            "leader",
            RouteDecision,
            "你是 Leader Agent。识别学习、生活或普通任务意图，提取用户明确提到的城市。未提地点使用北京。日期使用 YYYY-MM-DD。",
            f"今天是 {_today().isoformat()}。用户输入：{user_input}",
            lambda: _fallback_route(user_input),
            runs,
            progress,
        )
        keyword_route = _fallback_route(user_input)
        route.intents = list(dict.fromkeys([*route.intents, *keyword_route.intents]))
        try:
            target_date = date.fromisoformat(route.target_date)
        except ValueError:
            target_date = _today()
        if any(marker in user_input for marker in ("明天", "明晚", "后天")):
            target_date = date.fromisoformat(keyword_route.target_date)
        if target_date < _today():
            target_date = _today()

        news: list[NewsItem] = []
        learning: LearningOutput | None = None
        weather: dict = {}
        tasks: list[TaskDraft] = []
        tool_errors: list[str] = []

        general_tasks = _extract_general_tasks(user_input, target_date, route.location)
        tasks.extend(general_tasks)
        if progress and general_tasks:
            progress("leader", f"已保留 {len(general_tasks)} 个工作/产品任务")

        if "learning" in route.intents and len(runs) < 3:
            if progress:
                progress("learning", "正在从可信官方来源获取 AI 最新资讯")
            news, news_errors = fetch_ai_news()
            tool_errors.extend(news_errors)
            source_payload = json.dumps([item.model_dump(mode="json") for item in news], ensure_ascii=False)
            learning = self._call(
                "learning",
                LearningOutput,
                "你是 Learning Agent。只能依据给定官方资料生成中文学习摘要。必须生成恰好 3 道四选一单选题，答案必须可由资料或系统规则确定。建议学习时段不要与 19:00-20:00 运动冲突。",
                f"用户目标：{user_input}\n官方资料：{source_payload}",
                lambda: _fallback_learning(news),
                runs,
                progress,
            )
            start = _at(target_date, learning.suggested_start)
            tasks.append(TaskDraft(owner_agent="learning", task_type="learning", title=learning.task_title, description=learning.completion_criteria, location=route.location, priority="medium", start_at=start, due_at=start + timedelta(minutes=learning.duration_minutes), estimated_minutes=learning.duration_minutes))

        if "life" in route.intents and len(runs) < 3:
            exercise_minutes = _requested_exercise_minutes(user_input)
            if progress:
                progress("life", f"正在查询天气并生成 {exercise_minutes} 分钟运动方案")
            weather_target = _at(target_date, "19:00")
            try:
                weather = fetch_weather(route.location, weather_target)
            except Exception as exc:
                tool_errors.append(f"WeatherTool: {type(exc).__name__}")
                weather = {"city": route.location, "condition": "暂不可用", "precipitation_probability": 0, "error": str(exc)}
            life = self._call(
                "life",
                LifeOutput,
                f"你是 Life Management Agent。必须尊重用户明确要求的运动时长，本次为 {exercise_minutes} 分钟。工作日考虑 17:30 下班和 60 分钟通勤；周末不套用下班时间。23:00-24:00 入睡。根据天气选择室内或户外。",
                f"今天是否周末：{target_date.weekday() >= 5 or '周末' in user_input}\n用户目标：{user_input}\n天气：{json.dumps(weather, ensure_ascii=False)}",
                lambda: _fallback_life(weather, exercise_minutes),
                runs,
                progress,
            )
            life.duration_minutes = exercise_minutes
            life.task_title = f"完成 {exercise_minutes // 60} 小时运动" if exercise_minutes % 60 == 0 else f"完成 {exercise_minutes} 分钟运动"
            start = _at(target_date, life.suggested_start)
            tasks.append(TaskDraft(owner_agent="life", task_type="life", title=life.task_title, description=f"{life.plan}\n{life.weather_advice}\n备选：{life.indoor_alternative}", location=route.location, priority="low", start_at=start, due_at=start + timedelta(minutes=life.duration_minutes), estimated_minutes=life.duration_minutes))

        if "task" in route.intents and not tasks:
            start = _at(target_date, "19:00")
            tasks.append(TaskDraft(owner_agent="leader", task_type="task", title=user_input[:120], description="由用户输入生成的普通任务", location=route.location, priority="high" if re.search(r"截止|必须|前完成", user_input) else "medium", start_at=start, due_at=start + timedelta(hours=1), estimated_minutes=60))

        if progress:
            progress("scheduler", "正在按优先级排期并检查时间冲突")
        tasks = _schedule_tasks(tasks, target_date, user_input)
        conflicts = detect_conflicts(tasks)
        conflicts.extend([f"工具提示：{item}" for item in tool_errors])
        failed_agents = [run["agent_name"] for run in runs if run["status"] == "FAILED"]
        if failed_agents:
            conflicts.append(f"工具提示：{', '.join(failed_agents)} 模型调用失败，当前计划由本地规则生成；请重点检查内容后再确认。")
        if progress:
            progress("scheduler", f"已生成 {len(tasks)} 个任务，发现 {len(conflicts)} 条提示")
        return GeneratedPlan(request_id=request_id, target_date=target_date.isoformat(), tasks=tasks, conflicts=conflicts, learning=learning, news=news, weather=weather, agent_runs=runs)

    def review(self, facts: dict) -> ReviewOutput:
        try:
            result, _ = self.client.structured(
                ReviewOutput,
                "你是 Review Agent。只根据给定事实总结，不虚构原因。输出中文，建议必须具体且不超过 3 条。",
                json.dumps(facts, ensure_ascii=False, default=str),
            )
            return result
        except ModelUnavailable:
            total = facts.get("total", 0)
            completed = facts.get("completed", 0)
            return ReviewOutput(
                summary=f"今日共 {total} 项任务，完成 {completed} 项，完成率 {round(completed / total * 100) if total else 0}%。",
                wins=["已完成的任务已及时记录。"] if completed else [],
                issues=facts.get("reasons", []) or (["暂无任务执行记录。"] if not total else ["存在未完成任务。"]),
                suggestions=["明天优先安排最重要的一项任务，并保留 15 分钟缓冲。"],
            )


def detect_conflicts(tasks: list[TaskDraft]) -> list[str]:
    conflicts: list[str] = []
    ordered = sorted(tasks, key=lambda task: task.start_at)
    for task in ordered:
        if task.start_at >= task.due_at:
            conflicts.append(f"“{task.title}”的开始时间不得晚于截止时间。")
        if task.estimated_minutes > int((task.due_at - task.start_at).total_seconds() / 60):
            conflicts.append(f"“{task.title}”的预计时长超过可用时间窗口。")
        if task.due_at.time() > dt_time(23, 0):
            conflicts.append(f"“{task.title}”可能影响 23:00 后的睡眠安排。")
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_at < previous.due_at:
            conflicts.append(f"“{previous.title}”与“{current.title}”时间重叠。")
    return conflicts
