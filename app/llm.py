from __future__ import annotations

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings


T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.deepseek_model
        self.available = bool(settings.deepseek_api_key)
        self.client = (
            OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, timeout=45.0, max_retries=0)
            if self.available
            else None
        )

    def structured(self, schema: type[T], system_prompt: str, user_prompt: str) -> tuple[T, int]:
        if not self.client:
            raise ModelUnavailable("未配置 DEEPSEEK_API_KEY")
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        prompt = f"{user_prompt}\n\n请只返回 JSON，必须匹配以下 JSON Schema：\n{schema_json}"
        last_error: Exception | None = None
        for retry in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt + " 你必须只输出合法 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=5000,
                )
                raw = response.choices[0].message.content or ""
                return schema.model_validate_json(raw), retry
            except (json.JSONDecodeError, ValidationError, Exception) as exc:
                last_error = exc
        raise ModelUnavailable(f"模型结构化输出失败：{last_error}")

