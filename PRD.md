# 个人学习生活 Multi-Agent 管理平台 PRD

- 版本：V0.1
- 文档状态：已确认，可进入开发
- 目标上线时间：2026-09-19 上午
- 默认时区：Asia/Shanghai
- 默认城市：北京
- 产品形态：单用户、响应式 Web 应用

## 1. 产品目标

构建一个统一管理学习、任务、生活安排和每日复盘的个人智能工作台。用户只需描述当天目标，系统负责识别意图、拆解任务、查询实时信息、生成可执行计划，并在用户确认后跟踪执行和辅助复盘。

V0.1 优先解决：

1. 学习计划不合理、效率不高。
2. 一天内多个任务缺少排序和时间安排。
3. 学习、运动和生活安排分散。
4. 缺少逾期提醒、执行反馈和每日复盘。
5. “最新资讯”和天气建议容易依赖过时或虚构信息。

## 2. 用户价值

用户从“自己规划、查资料、记录和复盘”转变为“提出目标、确认方案、执行任务和反馈结果”。系统应帮助用户提升：

- 学习效率
- 执行力
- 知识复盘与沉淀
- 作息和生活规律

## 3. V0.1 核心演示闭环

用户输入：

> 今天下班后，我想学习了解 AI 最新的资讯，还想运动一个小时。

系统完成以下流程：

1. Leader Agent 识别学习和运动两个意图。
2. NewsTool 从可信官方来源获取最近 7 天的真实 AI 资讯。
3. WeatherTool 根据任务地点获取对应时段天气；未指定地点时使用北京。
4. Learning Agent 生成学习目标、资讯摘要、3 道单选题和完成标准。
5. Life Management Agent 结合天气、下班时间、通勤和作息生成运动建议。
6. Leader Agent 合并结果，检查时间冲突并形成计划草稿。
7. 用户手动修改任务名称、开始时间、截止时间和时长。
8. 用户确认计划后，任务进入正式执行状态。
9. 任务截止后仍未完成时，网页显示逾期提醒。
10. 用户将任务标记为已完成或未完成；未完成时填写原因。
11. 用户点击“生成今日复盘”，Review Agent 生成总结和明日建议。

## 4. 用户画像与默认约束

- 用户数量：仅一个用户。
- 默认城市：北京。
- 工作时间：09:00–17:30。
- 下班通勤：约 1 小时。
- 通常入睡时间：23:00–24:00。
- 目标睡眠时长：6–8 小时。
- 工作日学习预算：1 小时。
- 工作日运动预算：1 小时。
- 默认语言：中文。

时间规划需要保留晚餐、洗漱和任务切换缓冲，不得将全部可用时间无缝排满。

## 5. 产品范围

### 5.1 V0.1 必须实现

- 固定密码登录。
- 自然语言任务输入和多轮对话。
- Leader、Learning、Life Management、Review 四个 Agent。
- 实时 AI 官方资讯获取。
- 实时天气和小时级出行、运动建议。
- 计划草稿生成、编辑、冲突检测和确认。
- 今日任务展示和状态更新。
- 截止后网页提醒及稍后提醒。
- 学习摘要、3 道单选题、自动判分和掌握程度记录。
- 用户主动触发的今日复盘。
- Agent 执行日志和基础运行指标。
- 桌面端与手机端响应式页面。
- GitHub + Streamlit Community Cloud 公网部署。
- 本地 SQLite、公网 Supabase PostgreSQL。

### 5.2 V0.1 不实现

- 多用户注册和权限系统。
- 网页关闭后的消息提醒。
- 飞书、邮件或系统通知。
- 日历双向同步。
- 向量数据库和语义检索记忆。
- Agent 自主执行外部写操作。
- Agent 之间的自由调用。
- 自动将冲突任务顺延到次日。
- 简答题及大模型主观评分。
- 用户在设置页永久修改默认城市。

## 6. 页面与交互

### 6.1 桌面布局

- 左侧：今日任务、优先级、时间和状态操作。
- 中间：AI 对话、计划草稿、冲突提示、编辑与确认。
- 右侧：学习进度、掌握程度、Agent 当前状态和调用结果。
- 底部：今日复盘入口与复盘内容。

### 6.2 手机布局

按以下顺序纵向排列：

1. 今日概览
2. AI 对话与计划
3. 今日任务
4. 学习进度
5. Agent 状态
6. 今日复盘

任务表单采用单列布局，自测题选项整行可点击，逾期提醒显示在页面顶部。

### 6.3 计划编辑与确认

Agent 生成的内容首先进入草稿状态。确认前，用户可以修改：

- 任务名称
- 开始时间
- 截止时间
- 预计时长
- 优先级

未确认草稿可以通过对话直接修改。已经确认的任务只能先生成变更预览，经用户再次确认后修改。

## 7. Agent 架构

### 7.1 Leader Agent

职责：

- 理解用户意图。
- 抽取日期、时间、地点和任务类型。
- 决定需要调用的子 Agent 和确定性工具。
- 合并子 Agent 输出。
- 自动判断优先级。
- 发现时间冲突并生成处理建议。
- 输出计划草稿或变更预览。

Leader 是唯一调度入口。子 Agent 不允许调用其他 Agent。

### 7.2 Learning Agent

职责：

- 生成学习目标。
- 根据 NewsTool 返回的资料生成带来源摘要。
- 生成 3 道四选一单选题、答案和解析。
- 生成可验证的完成标准。
- 根据程序判分结果更新掌握程度。

Learning Agent 不得把模型自身知识描述为最新资讯。

### 7.3 Life Management Agent

职责：

- 生成运动和生活任务草稿。
- 根据工作、通勤、作息和可用时间安排任务。
- 根据 WeatherTool 输出运动形式、时段、装备和出行建议。
- 发现建议会影响睡眠时给出警告。

### 7.4 Review Agent

职责：

- 仅在用户点击“生成今日复盘”后运行。
- 读取当天任务状态、实际完成时间、未完成原因和学习测验结果。
- 输出完成情况、主要问题、知识掌握情况和明日建议。
- 不自动创建、改期或删除任务。

## 8. 确定性工具

### 8.1 NewsTool

- 数据源采用可信 AI 官方来源白名单。
- 初始来源包括 OpenAI、DeepSeek、Google AI、Anthropic 和 Hugging Face。
- 默认获取最近 7 天资讯。
- 返回 3–5 条结果。
- 按发布时间排序，并根据规范化链接和标题去重。
- 每条结果包含标题、来源、发布时间、原文链接和正文摘要所需内容。
- 单一来源失败不影响其他来源。
- 所有来源失败时明确提示，不允许模型用旧知识填充。

### 8.2 WeatherTool

- 使用 Open-Meteo 地理编码与天气预报接口。
- 默认地点为北京。
- 用户明确提到其他城市时，将该城市绑定到对应任务。
- 临时任务地点不会修改默认城市。
- 多城市任务分别查询天气。
- 城市存在歧义时在草稿中提示用户确认。
- 获取任务时段对应的温度、体感温度、降水概率、天气状态和风速。
- 接口失败时保留原计划并提示天气数据不可用。

### 8.3 ReminderService

- 不是 Agent，不调用模型。
- 网页打开时约每 30 秒查询一次逾期任务。
- 仅在任务截止且状态不是已完成时提醒。
- 操作包括：标记完成、稍后提醒、忽略本次。
- 稍后提醒默认 15 分钟，可选择 20 分钟。
- 同一任务最多重复提醒 3 次。
- 修改截止时间后，旧提醒失效。
- 使用唯一键防止页面刷新造成重复提醒。

## 9. 优先级与冲突规则

自动优先级顺序：

1. 有明确截止时间的任务。
2. 工作或必要事务。
3. 学习任务。
4. 运动与习惯任务。

同级任务按截止时间、预计时长和可用时间排序。优先级只影响排序和建议，不授权系统删除或改期任务。

以下情况视为冲突：

- 任务时间重叠。
- 总时长超过可用时间。
- 任务侵占最低睡眠约束。
- 开始时间晚于截止时间。
- 同一任务的预计时长大于时间窗口。

发生冲突时，系统必须保持草稿状态，列出原因并提供缩短、改期或删除低优先级任务等建议，等待用户决定。

## 10. 状态模型

### 10.1 计划状态

- `DRAFT`
- `WAITING_CONFIRMATION`
- `CONFIRMED`
- `REJECTED`
- `SUPERSEDED`

### 10.2 任务状态

- `PENDING`
- `CONFIRMED`
- `COMPLETED`
- `NOT_COMPLETED`
- `OVERDUE`
- `CANCELLED`

### 10.3 Agent 运行状态

- `QUEUED`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `SKIPPED`

## 11. 学习闭环

每个学习任务必须包含：

- 学习目标
- 带来源的材料摘要
- 3 道四选一单选题
- 完成标准
- 测验结果
- 掌握程度

掌握程度规则：

- 3/3：已掌握
- 2/3：基本掌握
- 0–1/3：需要复习
- 未提交：未评估

学习任务在用户完成阅读并提交测验后自动标记为已完成，用户也可以手动修改任务状态。首次提交用于当天掌握程度，后续提交记录为复习结果。

## 12. 任务反馈与复盘

用户更新任务时只需要选择：

- 已完成：记录实际完成时间。
- 未完成：必须选择或填写未完成原因。

默认未完成原因：

- 时间不足
- 临时事务
- 计划不合理
- 身体状态
- 缺乏动力
- 任务过难
- 其他

未完成任务不自动顺延。Review Agent 只能在复盘中提出建议。

每日复盘至少包含：

- 当日任务总数、完成数和完成率。
- 学习任务正确率与掌握程度。
- 未完成任务及原因汇总。
- 计划与执行之间的主要偏差。
- 明日 1–3 条可操作建议。

同一天重复生成复盘时更新当日复盘记录，不创建重复记录。

## 13. Human-in-the-loop 边界

以下动作必须确认：

- 首次确认整份计划。
- 修改已确认任务。
- 取消或删除任务。
- 批量调整多个任务。
- 将未完成任务改期到其他日期。

以下动作无需二次确认：

- 生成计划草稿。
- 查询新闻和天气。
- 修改未确认草稿。
- 提交单选题。
- 标记任务完成或未完成。
- 生成今日复盘。

Agent 不得自动修改已确认任务。

## 14. 可靠性设计

### 14.1 防止重复执行

- 每次用户请求生成 `request_id`。
- 每次 Agent 调用生成 `agent_run_id`。
- 每个任务只有一个 `owner_agent`。
- 确认、提醒和复盘写入采用幂等键。
- 用户重复点击提交时返回已有结果。

### 14.2 防止循环调用

- 只有 Leader 可以调度子 Agent。
- 子 Agent 无 Agent 调用权限。
- 单次计划生成最多调用 3 个 Agent：Leader、Learning、Life Management。
- Review Agent 作为独立用户操作，单次最多调用一次。
- 达到调用上限后立即停止并显示可理解的错误。

### 14.3 结构化输出校验

- Agent 输出必须符合 Pydantic Schema。
- DeepSeek 使用结构化 JSON 输出。
- 校验失败只重试一次。
- 仍失败时记录日志，并使用安全降级结果或提示用户重试。
- 禁止直接执行未经校验的工具参数和数据库写操作。

### 14.4 路由错误处理

- 页面显示 Leader 识别出的任务类型和 Agent 分配结果。
- 用户可在确认前修改任务类型。
- 路由修正写入日志，用于计算路由准确率。

### 14.5 用户目标突然修改

- 未确认计划可以直接更新。
- 已确认任务只生成变更预览。
- 用户确认后创建新版本并使旧版本失效。
- 所有变更保留审计记录。

### 14.6 外部服务失败

- DeepSeek、资讯源、天气接口分别设置超时。
- 单个资讯源失败时继续处理其他来源。
- 天气失败不阻断计划生成。
- DeepSeek 失败时保留用户输入和已抓取资料，允许重试。
- 页面必须展示真实失败状态，不伪造成功结果。

## 15. 数据设计

V0.1 最小数据表：

### `users`

- `id`
- `password_hash`
- `default_city`
- `timezone`
- `work_start_time`
- `work_end_time`
- `commute_minutes`
- `sleep_start_min`
- `sleep_start_max`
- `study_budget_minutes`
- `exercise_budget_minutes`

### `conversations`

- `id`
- `user_id`
- `created_at`
- `updated_at`

### `messages`

- `id`
- `conversation_id`
- `role`
- `content`
- `created_at`

### `plans`

- `id`
- `user_id`
- `request_id`
- `version`
- `status`
- `target_date`
- `conflict_summary`
- `confirmed_at`
- `created_at`

### `tasks`

- `id`
- `plan_id`
- `owner_agent`
- `task_type`
- `title`
- `description`
- `location`
- `priority`
- `start_at`
- `due_at`
- `estimated_minutes`
- `status`
- `not_completed_reason`
- `completed_at`
- `created_at`
- `updated_at`

### `learning_records`

- `id`
- `task_id`
- `topic`
- `learning_goal`
- `material_summary`
- `completion_criteria`
- `score`
- `mastery_level`
- `submitted_at`

### `learning_sources`

- `id`
- `learning_record_id`
- `source_name`
- `title`
- `published_at`
- `url`
- `fetched_at`

### `quiz_questions`

- `id`
- `learning_record_id`
- `question`
- `options_json`
- `correct_option`
- `explanation`

### `quiz_attempts`

- `id`
- `learning_record_id`
- `answers_json`
- `score`
- `is_initial_attempt`
- `submitted_at`

### `weather_snapshots`

- `id`
- `task_id`
- `city`
- `latitude`
- `longitude`
- `forecast_time`
- `weather_json`
- `fetched_at`

### `reminders`

- `id`
- `task_id`
- `scheduled_at`
- `reminder_type`
- `status`
- `attempt_count`
- `snoozed_until`
- 唯一约束：`task_id + reminder_type + scheduled_at`

### `daily_reviews`

- `id`
- `user_id`
- `review_date`
- `summary`
- `suggestions_json`
- `created_at`
- `updated_at`
- 唯一约束：`user_id + review_date`

### `agent_runs`

- `id`
- `request_id`
- `agent_name`
- `owner_task_id`
- `input_summary`
- `output_json`
- `status`
- `retry_count`
- `duration_ms`
- `error_code`
- `created_at`

### `task_change_logs`

- `id`
- `task_id`
- `change_source`
- `before_json`
- `after_json`
- `confirmed_by_user`
- `created_at`

## 16. 技术方案

- Python 3.12
- Streamlit：响应式 Web 页面
- SQLAlchemy：数据访问与本地/云数据库切换
- Pydantic：Agent、工具与表单数据校验
- Alembic：数据库结构迁移；若时间不足，V0.1 可用初始化脚本替代
- OpenAI Python SDK：调用 DeepSeek OpenAI-compatible API
- DeepSeek 模型：通过环境变量配置，默认 `deepseek-v4-pro`
- httpx：天气和资讯请求
- feedparser/BeautifulSoup：官方资讯源获取与解析
- passlib/bcrypt：固定访问密码校验
- pytest：核心状态机和幂等测试
- Streamlit Community Cloud：免费公网部署
- Supabase PostgreSQL：免费云端持久化

必要环境变量：

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DATABASE_URL
APP_PASSWORD_HASH
APP_TIMEZONE=Asia/Shanghai
```

## 17. 安全要求

- API Key、数据库密码和登录密码不得提交到 GitHub。
- 本地使用 `.env`，云端使用 Streamlit Secrets。
- `.env` 和 `secrets.toml` 必须加入 `.gitignore`。
- 所有外部 URL 只用于读取白名单来源。
- 任何模型输出在写入数据库或调用工具前必须完成 Schema 校验。
- Agent 日志不得保存 API Key 和完整数据库连接串。

## 18. 指标定义

### 路由准确率

`无需用户修正的任务路由数 / 总路由任务数`

### 任务完成率

`已完成任务数 / 已确认且到期任务数`

### 用户修改计划比例

`确认前被用户修改的计划数 / 生成的计划总数`

### 学习任务连续完成天数

连续存在至少一个已完成学习任务且提交自测的自然日数量。

### Agent 错误调用次数

状态为 `FAILED`、Schema 校验失败、工具参数非法或达到调用上限的 Agent 调用数量。

### 单任务平均 Agent 调用次数

`与任务关联的 Agent 调用总数 / 任务总数`

V0.1 只负责准确采集指标，不要求制作复杂分析看板。

## 19. 验收标准

明早版本必须通过以下演示：

1. 使用密码从桌面或手机登录公网地址。
2. 输入示例目标后，正确路由到 Learning 和 Life Management Agent。
3. 展示最近 7 天内带来源链接的真实 AI 资讯。
4. 展示北京对应时段天气和运动建议。
5. 生成无时间重叠、保留生活缓冲的计划草稿。
6. 用户可以修改名称、开始时间、截止时间和时长。
7. 用户确认后，任务进入今日任务列表。
8. 截止时间到达后，未完成任务在网页出现一次提醒。
9. “稍后提醒”可在 15 或 20 分钟后再次出现，且不重复轰炸。
10. 学习任务展示 3 道单选题并正确判分。
11. 用户可标记完成，或选择未完成并填写原因。
12. 点击“生成今日复盘”后展示完成率、学习掌握程度、未完成原因和明日建议。
13. 刷新页面或应用重新运行后，正式任务和复盘仍然存在。
14. Agent 运行日志能显示路由、耗时、成功状态和错误信息。
15. 手机页面可以完整完成输入、确认、答题、状态更新和复盘流程。

## 20. 今晚开发顺序

### 第一阶段：可运行骨架

1. 初始化项目、依赖和配置。
2. 建立 SQLAlchemy 模型和 SQLite/Supabase 连接。
3. 完成固定密码登录和响应式页面骨架。

### 第二阶段：主流程

1. 定义 Pydantic Agent Schema。
2. 实现 DeepSeek 客户端与重试。
3. 实现 Leader、Learning、Life Management Agent。
4. 实现计划草稿、编辑、冲突校验和确认。

### 第三阶段：实时工具与学习闭环

1. 实现 NewsTool 与来源白名单。
2. 实现 WeatherTool。
3. 实现学习摘要、单选题和判分。

### 第四阶段：提醒、复盘和部署

1. 实现逾期检测、提醒去重和稍后提醒。
2. 实现任务结果反馈与 Review Agent。
3. 添加 Agent 日志和指标采集。
4. 完成手机适配。
5. 推送 GitHub，连接 Supabase 和 Streamlit Community Cloud。
6. 按核心演示闭环执行一次完整验收。

## 21. 后续迭代

### V0.2

- 长期记忆和用户偏好学习。
- 学习主题历史、错题本和间隔复习。
- 更丰富的生活习惯统计。

### V0.3

- 日历同步。
- 飞书、邮件等网页关闭后的提醒。
- 更多资讯与工具来源。

### V1.0

- 多端个人长期智能工作台。
- 可配置 Agent 和自动化流程。
- 更完整的长期目标、知识和行为分析。
