# 个人学习生活 Multi-Agent 管理平台

一个单用户、可部署的 Streamlit MVP：将任务规划、AI 学习、天气建议、网页逾期提醒和每日复盘统一到一个入口。

## 本地启动

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run streamlit_app.py
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。未配置 Key 时，应用仍可使用降级计划运行，用于测试页面和状态流。

## 公网部署

1. 将代码推送到 GitHub。
2. 在 Supabase 创建免费 PostgreSQL 数据库，取得连接串。
3. 在 Streamlit Community Cloud 选择本仓库和 `streamlit_app.py`。
4. 在应用 Secrets 中设置：

```toml
DEEPSEEK_API_KEY = "..."
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DATABASE_URL = "postgresql://..."
APP_PASSWORD = "请设置强密码"
APP_TIMEZONE = "Asia/Shanghai"
```

不要将真实密钥写入仓库。

## 运行测试

```powershell
pytest -q
```

详细需求见 [PRD.md](PRD.md)。

