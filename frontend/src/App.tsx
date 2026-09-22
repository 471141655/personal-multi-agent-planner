import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Bot, BrainCircuit, CalendarDays, Check, ClipboardCheck, Dumbbell, LogOut, Send, Sparkles } from "lucide-react";
import { getDashboard, login, sendChat, setTaskResult, streamJob, submitQuiz } from "./api";
import type { AgentName, DashboardData, LearningRecord, Task } from "./types";

const reasons = ["时间不足", "临时事务", "计划不合理", "身体状态", "缺乏动力", "任务过难", "其他"];

function localDate(offset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offset);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function timeOf(value: string) {
  return value.slice(11, 16);
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const token = await login(password);
      localStorage.setItem("agent_token", token);
      onLogin(token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="login-mark"><BrainCircuit size={34} /></div>
        <p className="eyebrow">PERSONAL AGENT OS</p>
        <h1>学习与生活<br />智能工作台</h1>
        <p className="muted">一个入口管理目标、执行、学习和复盘。</p>
        <form onSubmit={submit}>
          <label htmlFor="password">访问密码</label>
          <input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
          {error && <p className="error-text">{error}</p>}
          <button className="primary-button" disabled={loading || !password}>{loading ? "验证中…" : "进入工作台"}</button>
        </form>
      </section>
    </main>
  );
}

function AgentHud({ agent, message }: { agent: AgentName | null; message: string }) {
  const config = {
    leader: { label: "LEADER", icon: Bot },
    learning: { label: "LEARNING AGENT", icon: BookOpen },
    life: { label: "LIFE AGENT", icon: Dumbbell },
    review: { label: "REVIEW AGENT", icon: ClipboardCheck },
    scheduler: { label: "SCHEDULER", icon: CalendarDays },
  } as const;
  const selected = agent ? config[agent] : { label: "MISSION COMPLETE", icon: Check };
  const Icon = selected.icon;
  return (
    <div className={`agent-hud ${agent ? "is-running" : "is-complete"}`}>
      <div className="avatar"><Icon size={25} /></div>
      <div><span>{selected.label}</span><p>{message || "Agent 团队已就绪"}</p></div>
    </div>
  );
}

function TaskCard({ task, token, onChanged }: { task: Task; token: string; onChanged: () => void }) {
  const [reason, setReason] = useState(reasons[0]);
  const [busy, setBusy] = useState(false);
  const closed = ["COMPLETED", "NOT_COMPLETED", "CANCELLED"].includes(task.status);

  async function update(completed: boolean) {
    setBusy(true);
    try {
      await setTaskResult(token, task.id, completed, completed ? undefined : reason);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="task-card">
      <div className="task-topline"><span className={`dot ${task.type}`} /><span>{timeOf(task.start_at)}–{timeOf(task.due_at)}</span><span className={`priority ${task.priority}`}>{task.priority}</span></div>
      <h3>{task.title}</h3>
      <p>{task.estimated_minutes} 分钟 · {task.owner_agent}</p>
      <div className={`status-pill ${task.status.toLowerCase()}`}>{task.status}</div>
      {task.not_completed_reason && <p className="reason">原因：{task.not_completed_reason}</p>}
      {!closed && (
        <div className="task-actions">
          <button disabled={busy} onClick={() => update(true)}>完成</button>
          <select value={reason} onChange={(event) => setReason(event.target.value)}>{reasons.map((item) => <option key={item}>{item}</option>)}</select>
          <button className="ghost-danger" disabled={busy} onClick={() => update(false)}>未完成</button>
        </div>
      )}
    </article>
  );
}

function Quiz({ record, token, onChanged }: { record: LearningRecord; token: string; onChanged: () => void }) {
  const [answers, setAnswers] = useState<Array<number | null>>(record.quiz.map(() => null));
  const [error, setError] = useState("");
  if (record.score !== null) return <div className="quiz-score"><strong>{record.score}/3</strong><span>{record.mastery}</span></div>;

  async function submit() {
    if (answers.some((answer) => answer === null)) {
      setError("请完成全部题目");
      return;
    }
    await submitQuiz(token, record.id, answers as number[]);
    onChanged();
  }

  return (
    <div className="quiz">
      {record.quiz.map((question, questionIndex) => (
        <fieldset key={question.question}>
          <legend>{questionIndex + 1}. {question.question}</legend>
          {question.options.map((option, optionIndex) => (
            <label key={option}><input type="radio" name={`q-${record.id}-${questionIndex}`} checked={answers[questionIndex] === optionIndex} onChange={() => setAnswers((current) => current.map((item, index) => index === questionIndex ? optionIndex : item))} />{option}</label>
          ))}
        </fieldset>
      ))}
      {error && <p className="error-text">{error}</p>}
      <button onClick={submit}>提交自测</button>
    </div>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("agent_token") ?? "");
  const [selectedDate, setSelectedDate] = useState(localDate());
  const [data, setData] = useState<DashboardData | null>(null);
  const [input, setInput] = useState("");
  const [pendingRequest, setPendingRequest] = useState("");
  const [agent, setAgent] = useState<AgentName | null>(null);
  const [agentMessage, setAgentMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chatRef = useRef<HTMLDivElement>(null);
  const messageCount = useRef(0);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setData(await getDashboard(token, selectedDate));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败");
    }
  }, [token, selectedDate]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!chatRef.current || !data || data.messages.length === messageCount.current) return;
    const element = chatRef.current;
    const wasNearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 120 || messageCount.current === 0;
    messageCount.current = data.messages.length;
    if (wasNearBottom) requestAnimationFrame(() => { element.scrollTop = element.scrollHeight; });
  }, [data?.messages.length]);

  const stats = useMemo(() => {
    const tasks = data?.tasks ?? [];
    const done = tasks.filter((task) => task.status === "COMPLETED").length;
    return { total: tasks.length, done, rate: tasks.length ? Math.round(done / tasks.length * 100) : 0 };
  }, [data?.tasks]);

  async function handleJob(jobId: string) {
    await streamJob(token, jobId, (event, payload) => {
      if (event === "started" || event === "progress") {
        setAgent((payload.agent as AgentName) || "leader");
        setAgentMessage(String(payload.message ?? "正在处理"));
      }
      if (event === "failed") setError(String(payload.message ?? "Agent 执行失败"));
      if (event === "completed" || event === "failed") {
        setAgent(null);
        setAgentMessage("");
      }
    });
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError("");
    try {
      const response = await sendChat(token, text, pendingRequest || undefined);
      if (response.action === "clarification") setPendingRequest(response.pending_request ?? text);
      else setPendingRequest("");
      if (response.action === "job" && response.job_id) await handleJob(response.job_id);
      if (response.action === "confirmed" && response.target_date) setSelectedDate(response.target_date);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <Login onLogin={setToken} />;

  const dateOptions = [{ label: "昨日", value: localDate(-1) }, { label: "今日", value: localDate() }, { label: "明日", value: localDate(1) }];
  return (
    <main className="app-shell">
      <header className="topbar">
        <div><p className="eyebrow">PERSONAL AGENT OS</p><h1>智能工作台</h1></div>
        <button className="icon-button" aria-label="退出" onClick={() => { localStorage.removeItem("agent_token"); setToken(""); }}><LogOut size={19} /></button>
      </header>

      <nav className="date-nav">
        {dateOptions.map((item) => <button key={item.value} className={selectedDate === item.value ? "active" : ""} onClick={() => setSelectedDate(item.value)}>{item.label}</button>)}
        <input aria-label="选择日期" type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
      </nav>

      <section className="overview-grid">
        <div className="stat"><span>任务</span><strong>{stats.total}</strong></div>
        <div className="stat"><span>已完成</span><strong>{stats.done}</strong></div>
        <div className="stat"><span>完成率</span><strong>{stats.rate}%</strong></div>
        <AgentHud agent={agent} message={agentMessage} />
      </section>

      {error && <div className="global-error">{error}</div>}

      <section className="workspace-grid">
        <aside className="panel task-panel">
          <div className="panel-title"><div><span>DAILY FLOW</span><h2>{selectedDate} 任务</h2></div><CalendarDays size={20} /></div>
          <div className="panel-scroll">
            {data?.tasks.length ? data.tasks.map((task) => <TaskCard key={task.id} task={task} token={token} onChanged={refresh} />) : <div className="empty">这个日期还没有已确认任务</div>}
          </div>
        </aside>

        <section className="panel chat-panel">
          <div className="panel-title"><div><span>ORCHESTRATION</span><h2>AI 对话与计划</h2></div><Sparkles size={20} /></div>
          <div className="chat-scroll" ref={chatRef}>
            {data?.messages.length ? data.messages.map((message) => (
              <div className={`message ${message.role}`} key={message.id}>
                <div className="message-label">{message.role === "user" ? "YOU" : "AGENT"}</div>
                <p>{message.content}</p>
                <time>{new Date(message.created_at).toLocaleString("zh-CN", { hour12: false })}</time>
              </div>
            )) : <div className="empty">告诉 Agent 你想完成什么，它会先确认时间再安排。</div>}
          </div>
          {pendingRequest && <div className="pending-context">正在等待你补充可开始时间；输入“取消”可停止。</div>}
          <p className="quick-prompts">快捷指令：确认计划 · 生成今日复盘</p>
          <form className="chat-form" onSubmit={send}>
            <textarea rows={2} value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入计划、修改要求或快捷指令…" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
            <button aria-label="发送" disabled={busy || !input.trim()}><Send size={20} /></button>
          </form>
        </section>

        <aside className="panel learning-panel">
          <div className="panel-title"><div><span>LEARNING LOOP</span><h2>学习进度</h2></div><BookOpen size={20} /></div>
          <div className="learning-summary">
            <div><strong>{data?.learning_summary.total ?? 0}</strong><span>累计学习</span></div>
            <div><strong>{data?.learning_summary.streak ?? 0}</strong><span>连续天数</span></div>
            <div><strong>{data?.learning_summary.average_score ?? "—"}</strong><span>平均得分</span></div>
          </div>
          <div className="panel-scroll">
            {data?.tasks.filter((task) => task.learning).map((task) => (
              <article className="learning-card" key={task.id}>
                <h3>{task.title}</h3>
                <p>{task.learning!.goal}</p>
                <details><summary>学习摘要与自测</summary><p>{task.learning!.material_summary}</p><Quiz record={task.learning!} token={token} onChanged={refresh} /></details>
              </article>
            ))}
            {!data?.tasks.some((task) => task.learning) && <div className="empty">所选日期暂无学习任务</div>}
          </div>
        </aside>
      </section>
    </main>
  );
}

export default App;
