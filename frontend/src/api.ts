import type { ChatResponse, DashboardData } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function checked(response: Response) {
  if (response.status === 401) {
    localStorage.removeItem("agent_token");
    window.location.reload();
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(payload.detail ?? `HTTP ${response.status}`);
  }
  return response;
}

export async function login(password: string): Promise<string> {
  const response = await checked(
    await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }),
  );
  const payload = await response.json();
  return payload.access_token;
}

export async function getDashboard(token: string, date: string): Promise<DashboardData> {
  const response = await checked(
    await fetch(`${API_BASE}/api/dashboard?target_date=${date}`, { headers: authHeaders(token) }),
  );
  return response.json();
}

export async function sendChat(token: string, text: string, pendingRequest?: string): Promise<ChatResponse> {
  const response = await checked(
    await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ text, pending_request: pendingRequest || null }),
    }),
  );
  return response.json();
}

export async function setTaskResult(token: string, taskId: number, completed: boolean, reason?: string) {
  const response = await checked(
    await fetch(`${API_BASE}/api/tasks/${taskId}/result`, {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify({ completed, reason: reason || null }),
    }),
  );
  return response.json();
}

export async function submitQuiz(token: string, recordId: number, answers: number[]) {
  const response = await checked(
    await fetch(`${API_BASE}/api/learning/${recordId}/quiz`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ answers }),
    }),
  );
  return response.json();
}

export async function streamJob(
  token: string,
  jobId: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
) {
  const response = await checked(
    await fetch(`${API_BASE}/api/jobs/${jobId}/events`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    }),
  );
  const reader = response.body?.getReader();
  if (!reader) throw new Error("浏览器不支持实时事件流");
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let eventName = "message";
      let data = "{}";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      const parsed = JSON.parse(data);
      onEvent(eventName, parsed.data ?? {});
    }
  }
}
