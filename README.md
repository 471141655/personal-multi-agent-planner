# 个人学习生活 Multi-Agent 管理平台

一个单用户的学习生活智能工作台。新架构使用 React + Vite + TypeScript 前端、FastAPI API、SSE Agent 进度、独立 Worker 和 PostgreSQL/Supabase。原 Streamlit 入口暂时保留作为回退版本。

## 架构

```text
React Web / 飞书机器人
          ↓
       FastAPI ── SSE Agent 进度
          ↓
Agent Orchestrator ── DeepSeek / 资讯 / 天气
          ↓
Supabase PostgreSQL ← Worker 逾期任务与复盘通知
```

## 本地启动新架构

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env

# 终端 1：API（同时托管已构建前端）
uvicorn app.api:app --reload --port 8000

# 终端 2：背景任务
python -m app.worker

# 终端 3：React 开发服务器
cd frontend
npm install
npm run dev
```

生产构建：

```powershell
cd frontend
npm ci
npm run build
cd ..
uvicorn app.api:app --host 0.0.0.0 --port 8000 --workers 1
```

也可以使用 `docker compose up --build`。API 必须保持单 worker，当前 SSE Job 状态存储在 API 进程内。

## 飞书企业自建应用

1. 在飞书开放平台创建企业自建应用并开启机器人。
2. 申请接收用户消息和发送消息权限。
3. 订阅 `im.message.receive_v1`，HTTP 事件地址填写 `https://<API域名>/api/feishu/events`。
4. 卡片回调地址填写 `https://<API域名>/api/feishu/card-actions`。
5. 配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`、`FEISHU_OWNER_OPEN_ID`。
6. 发布应用版本并安装到当前企业。

飞书入站事件使用唯一索引去重；耗时 Agent 任务在返回事件 ACK 后执行。开发时请使用飞书的测试企业和测试版本。

## Streamlit 回退入口

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run streamlit_app.py
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。未配置 Key 时，应用仍可使用降级计划运行，用于测试页面和状态流。

## 公网部署（新架构）

新架构需要一个能够持续运行 Docker 容器（或两个 Python 进程）的公网主机。Streamlit Community Cloud 只能继续承载回退版，不能同时运行 FastAPI 与后台 Worker。

部署步骤：

1. 将代码推送到 GitHub，并在 Supabase 取得 PostgreSQL 连接串。
2. 在支持 Docker 的主机上使用仓库根目录的 `Dockerfile` 部署 API；同一镜像再创建一个 Worker 服务，并把启动命令改为 `python -m app.worker`。
3. API 与 Worker 使用相同的环境变量；只将 API 暴露到公网。
4. API 健康检查地址设置为 `/api/health`，确认返回 `{"status":"ok"}`。
5. 将飞书事件订阅与卡片回调地址指向这个 API 域名。

必需环境变量：

```toml
DEEPSEEK_API_KEY = "..."
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DATABASE_URL = "postgresql://..."
APP_PASSWORD = "请设置强密码"
APP_TIMEZONE = "Asia/Shanghai"
FRONTEND_ORIGINS = "https://你的域名"
```

启用飞书时再增加：

```toml
FEISHU_APP_ID = "cli_..."
FEISHU_APP_SECRET = "..."
FEISHU_VERIFICATION_TOKEN = "..."
FEISHU_OWNER_OPEN_ID = "ou_..."
```

`docker-compose.yml` 可用于本地或单台服务器快速启动。若平台把 API 与 Worker 拆成两个服务，应分别使用 `uvicorn app.api:app --host 0.0.0.0 --port 8000 --workers 1` 与 `python -m app.worker`。

### Railway 单服务低成本部署

仓库包含 `railway.toml` 和 `app.railway` 启动入口。Railway 部署时会运行一个 Uvicorn 进程，并在同一容器中启动一个守护 Worker 线程，以减少个人 MVP 的服务数量和费用。

1. 在 Railway 使用 GitHub 仓库创建项目。
2. 选择 Hobby 计划并设置消费上限提醒。
3. 添加 `DATABASE_URL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`APP_PASSWORD` 和 `APP_TIMEZONE`。
4. 在 Networking 中生成 Railway Domain。
5. 将 `FRONTEND_ORIGINS` 设置为生成的 HTTPS 域名。
6. 健康检查 `/api/health` 通过后，再配置飞书变量和回调地址。

Railway 必须保持单副本；当前 SSE Job 状态存储在 API 内存中，多个副本会导致事件流无法找到对应 Job。生产规模扩大后应改用 Redis/任务队列并重新拆分 Worker。

## Streamlit 公网回退版

现有 Streamlit Community Cloud 应用可以继续使用：在应用设置中选择 `streamlit_app.py`，并保留已有 Secrets。它不会提供 React、SSE、Worker 或飞书入口，仅作为迁移期间的稳定回退版本。

不要将真实密钥写入仓库。

## 运行测试

```powershell
pytest -q
```

详细需求见 [PRD.md](PRD.md)。
