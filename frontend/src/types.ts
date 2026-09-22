export type AgentName = "leader" | "learning" | "life" | "review" | "scheduler";

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface LearningRecord {
  id: number;
  topic: string;
  goal: string;
  material_summary: string;
  completion_criteria: string;
  sources: Array<{ title: string; url: string; source: string }>;
  quiz: Array<{ question: string; options: string[] }>;
  score: number | null;
  mastery: string;
}

export interface Task {
  id: number;
  title: string;
  description: string;
  type: string;
  owner_agent: string;
  priority: string;
  start_at: string;
  due_at: string;
  estimated_minutes: number;
  status: string;
  not_completed_reason: string | null;
  learning: LearningRecord | null;
}

export interface Plan {
  id: number;
  status: string;
  target_date: string;
  conflicts: string[];
  tasks: Task[];
}

export interface DashboardData {
  selected_date: string;
  today: string;
  tasks: Task[];
  messages: Message[];
  draft: Plan | null;
  learning_summary: {
    total: number;
    assessed: number;
    average_score: number | null;
    latest_mastery: string;
    streak: number;
  };
}

export interface ChatResponse {
  action: "message" | "clarification" | "job" | "confirmed" | "updated";
  message?: Message;
  pending_request?: string;
  job_id?: string;
  kind?: string;
  target_date?: string;
}
