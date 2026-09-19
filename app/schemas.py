from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RouteDecision(BaseModel):
    intents: list[Literal["learning", "life", "task"]]
    location: str = "北京"
    target_date: str
    rationale: str = ""


class NewsItem(BaseModel):
    title: str
    source: str
    published_at: datetime | None = None
    url: str
    excerpt: str = ""


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str


class LearningOutput(BaseModel):
    task_title: str
    learning_goal: str
    material_summary: str
    completion_criteria: str
    suggested_start: str = "20:30"
    duration_minutes: int = Field(default=60, ge=15, le=180)
    quiz: list[QuizQuestion] = Field(min_length=3, max_length=3)

    @field_validator("suggested_start")
    @classmethod
    def validate_time(cls, value: str) -> str:
        datetime.strptime(value, "%H:%M")
        return value


class LifeOutput(BaseModel):
    task_title: str
    plan: str
    weather_advice: str
    suggested_start: str = "19:00"
    duration_minutes: int = Field(default=60, ge=10, le=180)
    indoor_alternative: str

    @field_validator("suggested_start")
    @classmethod
    def validate_time(cls, value: str) -> str:
        datetime.strptime(value, "%H:%M")
        return value


class TaskDraft(BaseModel):
    owner_agent: Literal["leader", "learning", "life"]
    task_type: Literal["learning", "life", "task"]
    title: str
    description: str
    location: str = "北京"
    priority: Literal["high", "medium", "low"]
    start_at: datetime
    due_at: datetime
    estimated_minutes: int = Field(ge=5, le=720)


class GeneratedPlan(BaseModel):
    request_id: str
    target_date: str
    tasks: list[TaskDraft]
    conflicts: list[str] = []
    learning: LearningOutput | None = None
    news: list[NewsItem] = []
    weather: dict = {}
    agent_runs: list[dict] = []


class ReviewOutput(BaseModel):
    summary: str
    wins: list[str]
    issues: list[str]
    suggestions: list[str] = Field(min_length=1, max_length=3)

