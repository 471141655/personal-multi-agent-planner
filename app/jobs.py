from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

from app.timeutils import now_local


@dataclass
class JobEvent:
    sequence: int
    event: str
    data: dict
    created_at: datetime = field(default_factory=now_local)

    def as_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "event": self.event,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class JobState:
    id: str
    kind: str
    status: str = "QUEUED"
    events: list[JobEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, JobState] = {}

    def create(self, kind: str) -> JobState:
        job = JobState(id=uuid.uuid4().hex, kind=kind)
        self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        return self.jobs.get(job_id)

    async def publish(self, job_id: str, event: str, data: dict) -> None:
        job = self.jobs[job_id]
        if event == "started":
            job.status = "RUNNING"
        elif event == "completed":
            job.status = "COMPLETED"
        elif event == "failed":
            job.status = "FAILED"
        async with job.condition:
            job.events.append(JobEvent(sequence=len(job.events) + 1, event=event, data=data))
            job.condition.notify_all()

    async def stream(self, job_id: str, after: int = 0) -> AsyncIterator[JobEvent]:
        job = self.jobs[job_id]
        cursor = max(after, 0)
        while True:
            heartbeat = False
            async with job.condition:
                while len(job.events) <= cursor and job.status not in {"COMPLETED", "FAILED"}:
                    try:
                        await asyncio.wait_for(job.condition.wait(), timeout=15)
                    except TimeoutError:
                        heartbeat = True
                        break
                pending = job.events[cursor:]
            if heartbeat:
                yield JobEvent(sequence=cursor, event="heartbeat", data={})
            for event in pending:
                cursor = event.sequence
                yield event
            if job.status in {"COMPLETED", "FAILED"} and len(job.events) <= cursor:
                break


job_manager = JobManager()
