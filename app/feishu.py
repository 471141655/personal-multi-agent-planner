from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import get_settings


class FeishuClient:
    base_url = "https://open.feishu.cn/open-apis"

    def __init__(self) -> None:
        settings = get_settings()
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token = ""
        self._token_expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def tenant_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if not self.configured:
            raise RuntimeError("未配置 FEISHU_APP_ID/FEISHU_APP_SECRET")
        response = httpx.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"飞书 token 获取失败：{payload}")
        self._token = payload["tenant_access_token"]
        self._token_expires_at = time.time() + int(payload.get("expire", 7200))
        return self._token

    def send(self, receive_id: str, msg_type: str, content: dict[str, Any]) -> dict:
        token = self.tenant_access_token()
        response = httpx.post(
            f"{self.base_url}/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={"receive_id": receive_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"飞书消息发送失败：{payload}")
        return payload

    def send_text(self, receive_id: str, text: str) -> dict:
        return self.send(receive_id, "text", {"text": text})

    def send_plan_card(self, receive_id: str, plan_id: int, title: str, lines: list[str]) -> dict:
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
            "elements": [
                {"tag": "markdown", "content": "\n".join(lines)},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "确认计划"},
                            "type": "primary",
                            "value": {"action": "confirm_plan", "plan_id": plan_id},
                        }
                    ],
                },
            ],
        }
        return self.send(receive_id, "interactive", card)


feishu_client = FeishuClient()
