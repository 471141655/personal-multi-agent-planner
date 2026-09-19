from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta

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
from app.timeutils import today_local


KNOWN_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "天津", "重庆", "苏州"]


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
    return RouteDecision(intents=intents, location=city, target_date=_today().isoformat(), rationale="关键词安全路由")


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


def _fallback_life(weather: dict) -> LifeOutput:
    rain = int(weather.get("precipitation_probability", 0) or 0)
    indoor = rain >= 50
    return LifeOutput(
        task_title="完成 1 小时运动",
        plan="完成热身 10 分钟、主体训练 40 分钟和拉伸 10 分钟。",
        weather_advice=(f"{weather.get('city', '北京')} {weather.get('condition', '天气未知')}，降水概率 {rain}%。" + ("建议室内运动。" if indoor else "可以考虑户外运动。")),
        suggested_start="19:00",
        duration_minutes=60,
        indoor_alternative="室内徒手训练或瑜伽 60 分钟。",
    )


class PlannerOrchestrator:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()

    def _call(self, name: str, schema, system: str, user: str, fallback, runs: list[dict]):
        started = time.perf_counter()
        try:
            result, retries = self.client.structured(schema, system, user)
            runs.append({"agent_name": name, "status": "SUCCEEDED", "retry_count": retries, "duration_ms": int((time.perf_counter() - started) * 1000), "output_json": result.model_dump(mode="json")})
            return result
        except ModelUnavailable as exc:
            result = fallback()
            runs.append({"agent_name": name, "status": "FAILED", "retry_count": 1, "duration_ms": int((time.perf_counter() - started) * 1000), "error_code": str(exc)[:100], "output_json": result.model_dump(mode="json")})
            return result

    def generate(self, user_input: str) -> GeneratedPlan:
        request_id = uuid.uuid4().hex
        runs: list[dict] = []
        route = self._call(
            "leader",
            RouteDecision,
            "你是 Leader Agent。识别学习、生活或普通任务意图，提取用户明确提到的城市。未提地点使用北京。日期使用 YYYY-MM-DD。",
            f"今天是 {_today().isoformat()}。用户输入：{user_input}",
            lambda: _fallback_route(user_input),
            runs,
        )
        try:
            target_date = date.fromisoformat(route.target_date)
        except ValueError:
            target_date = _today()
        if target_date < _today():
            target_date = _today()

        news: list[NewsItem] = []
        learning: LearningOutput | None = None
        weather: dict = {}
        tasks: list[TaskDraft] = []
        tool_errors: list[str] = []

        if "learning" in route.intents and len(runs) < 3:
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
            )
            start = _at(target_date, learning.suggested_start)
            tasks.append(TaskDraft(owner_agent="learning", task_type="learning", title=learning.task_title, description=learning.completion_criteria, location=route.location, priority="medium", start_at=start, due_at=start + timedelta(minutes=learning.duration_minutes), estimated_minutes=learning.duration_minutes))

        if "life" in route.intents and len(runs) < 3:
            weather_target = _at(target_date, "19:00")
            try:
                weather = fetch_weather(route.location, weather_target)
            except Exception as exc:
                tool_errors.append(f"WeatherTool: {type(exc).__name__}")
                weather = {"city": route.location, "condition": "暂不可用", "precipitation_probability": 0, "error": str(exc)}
            life = self._call(
                "life",
                LifeOutput,
                "你是 Life Management Agent。用户 17:30 下班、通勤 60 分钟、23:00-24:00 入睡。生成可执行的 1 小时运动建议，保留晚餐和切换缓冲；根据天气选择室内或户外。建议时段不要与 20:30-21:30 学习冲突。",
                f"用户目标：{user_input}\n天气：{json.dumps(weather, ensure_ascii=False)}",
                lambda: _fallback_life(weather),
                runs,
            )
            start = _at(target_date, life.suggested_start)
            tasks.append(TaskDraft(owner_agent="life", task_type="life", title=life.task_title, description=f"{life.plan}\n{life.weather_advice}\n备选：{life.indoor_alternative}", location=route.location, priority="low", start_at=start, due_at=start + timedelta(minutes=life.duration_minutes), estimated_minutes=life.duration_minutes))

        if "task" in route.intents and not tasks:
            start = _at(target_date, "19:00")
            tasks.append(TaskDraft(owner_agent="leader", task_type="task", title=user_input[:120], description="由用户输入生成的普通任务", location=route.location, priority="high" if re.search(r"截止|必须|前完成", user_input) else "medium", start_at=start, due_at=start + timedelta(hours=1), estimated_minutes=60))

        conflicts = detect_conflicts(tasks)
        conflicts.extend([f"工具提示：{item}" for item in tool_errors])
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
