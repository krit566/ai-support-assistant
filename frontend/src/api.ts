// Typed client for the HelpDesk AI API. Every call goes through `request`, which adds the session token,
// turns error responses into ApiError with the server's message, and signs the user out on 401.

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export interface User {
  id: number;
  name: string;
  email: string;
  role: "admin" | "agent";
}
export interface Session {
  token: string;
  user: User;
  workspace: string;
}
export interface Kb {
  id: number;
  name: string;
  slug: string;
  description: string;
  team_name: string;
  fallback_message: string;
  created_at: string;
  document_count: number;
  chunk_count: number;
  questions_7d: number;
}
export interface Doc {
  id: number;
  filename: string;
  doc_key: string;
  title: string;
  kind: "pdf" | "markdown" | "text";
  size_bytes: number;
  version: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}
export interface ChunkRow {
  id: number;
  ordinal: number;
  section: string;
  text: string;
}
export interface Passage {
  source: string;
  title: string;
  section: string;
  text: string;
  document_id?: number | null;
  chunk_id?: number | null;
}
export interface Answer {
  conversation_id: number;
  message_id: number;
  text: string;
  abstained: boolean;
  mode: string;
  sources: Passage[];
  note: string;
}
export interface ConversationRow {
  id: number;
  channel: "console" | "public";
  is_demo: boolean;
  created_at: string;
  first_question: string;
  messages: number;
  refused: number;
  rating_down: number;
}
export interface MessageRow {
  id: number;
  role: "user" | "assistant";
  text: string;
  sources: Passage[] | null;
  abstained: boolean;
  mode: string | null;
  created_at: string;
  rating: number | null;
}
export interface Analytics {
  days: number;
  questions: number;
  answered: number;
  refused: number;
  refusal_rate: number;
  feedback: { up: number; down: number };
  modes: Record<string, number>;
  latency_ms: { p50: number | null; p95: number | null };
  series: { date: string; questions: number; refused: number }[];
  gaps: { topic: string; count: number; examples: string[] }[];
  low_rated: { message_id: number; question: string; answer: string; sources: string[]; comment: string; at: string }[];
}
export interface KeyRow {
  id: number;
  name: string;
  prefix: string;
  rate_per_minute: number;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}
export interface KbSettings {
  embedder: string;
  retrieval: string;
  thresholds: { min_dense: number; min_bm25: number };
  thresholds_source: string;
  llm_answers: boolean;
  max_upload_mb: number;
  public_rate_default: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "helpdesk.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage can be blocked (private mode); the user then signs in each visit
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

let onUnauthorized: () => void = () => {};
export function handleUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

function detail(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return `${d[0].loc?.slice(-1)[0] ?? "input"}: ${d[0].msg}`; // FastAPI 422
  return fallback;
}

export async function request<T>(path: string, init: RequestInit & { apiKey?: string } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token && !init.apiKey) headers.set("Authorization", `Bearer ${token}`);
  if (init.apiKey) headers.set("X-API-Key", init.apiKey);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(API_URL + path, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !init.apiKey && token) onUnauthorized();
    throw new ApiError(res.status, detail(body, `Request failed (${res.status})`));
  }
  return body as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  login: (email: string, password: string) => request<Session>("/api/auth/login", { method: "POST", body: json({ email, password }) }),
  signup: (b: { workspace: string; name: string; email: string; password: string }) =>
    request<Session>("/api/auth/signup", { method: "POST", body: json(b) }),
  me: () => request<Session>("/api/auth/me"),

  kbs: () => request<Kb[]>("/api/kbs"),
  kb: (id: number) => request<Kb>(`/api/kbs/${id}`),
  createKb: (b: { name: string; slug: string; description: string; team_name: string; fallback_message: string }) =>
    request<Kb>("/api/kbs", { method: "POST", body: json(b) }),
  updateKb: (id: number, b: Partial<Pick<Kb, "name" | "description" | "team_name" | "fallback_message">>) =>
    request<Kb>(`/api/kbs/${id}`, { method: "PATCH", body: json(b) }),
  settings: (id: number) => request<KbSettings>(`/api/kbs/${id}/settings`),

  documents: (kb: number) => request<Doc[]>(`/api/kbs/${kb}/documents`),
  upload: (kb: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Doc>(`/api/kbs/${kb}/documents`, { method: "POST", body: fd });
  },
  chunks: (doc: number) => request<ChunkRow[]>(`/api/documents/${doc}/chunks`),
  reindex: (doc: number) => request<Doc>(`/api/documents/${doc}/reindex`, { method: "POST" }),
  deleteDoc: (doc: number) => request<void>(`/api/documents/${doc}`, { method: "DELETE" }),

  ask: (kb: number, question: string, conversation_id?: number) =>
    request<Answer>(`/api/kbs/${kb}/ask`, { method: "POST", body: json({ question, conversation_id }) }),
  conversations: (kb: number, onlyProblems = false) =>
    request<ConversationRow[]>(`/api/kbs/${kb}/conversations${onlyProblems ? "?only_problems=true" : ""}`),
  conversation: (id: number) => request<MessageRow[]>(`/api/conversations/${id}`),
  feedback: (message: number, rating: 1 | -1, comment = "") =>
    request<void>(`/api/messages/${message}/feedback`, { method: "PUT", body: json({ rating, comment }) }),
  analytics: (kb: number, days = 30) => request<Analytics>(`/api/kbs/${kb}/analytics?days=${days}`),

  keys: (kb: number) => request<KeyRow[]>(`/api/kbs/${kb}/keys`),
  createKey: (kb: number, name: string, rate_per_minute: number) =>
    request<KeyRow & { key: string }>(`/api/kbs/${kb}/keys`, { method: "POST", body: json({ name, rate_per_minute }) }),
  revokeKey: (kb: number, id: number) => request<KeyRow>(`/api/kbs/${kb}/keys/${id}`, { method: "DELETE" }),

  publicKb: (slug: string, key: string) => request<{ name: string; description: string; team_name: string }>(`/api/public/kbs/${slug}`, { apiKey: key }),
  publicAsk: (slug: string, key: string, question: string, conversation_id?: number) =>
    request<Answer>(`/api/public/kbs/${slug}/ask`, { method: "POST", body: json({ question, conversation_id }), apiKey: key }),
  publicFeedback: (slug: string, key: string, message: number, rating: 1 | -1) =>
    request<void>(`/api/public/kbs/${slug}/messages/${message}/feedback`, { method: "PUT", body: json({ rating }), apiKey: key }),
};

// "07-one-offer-policy#dream-companies" style ids are fine for machines; people see "Title › Section"
export const citeLabel = (p: Pick<Passage, "title" | "section">) => `${p.title} › ${p.section}`;

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
