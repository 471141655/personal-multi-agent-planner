from __future__ import annotations

import os

# Railway 使用单容器低成本部署；API 启动时同时拉起一个守护 Worker 线程。
os.environ.setdefault("RUN_EMBEDDED_WORKER", "true")

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
