import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../auth";

type Handler = (init: RequestInit, url: string) => unknown | Promise<unknown>;
export interface Call {
  method: string;
  url: string;
  headers: Headers;
  body: unknown;
}

// Fake API: routes like "GET /api/kbs" -> handler. Records every call so tests can check what was sent.
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const headers = new Headers(init.headers);
    calls.push({ method, url: path, headers, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body });
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.split(" ");
      return m === method && (p === path || p === path.split("?")[0]);
    });
    if (!key) return new Response(JSON.stringify({ detail: `no mock for ${method} ${path}` }), { status: 404 });
    const h = routes[key];
    const out = typeof h === "function" ? await (h as Handler)(init, path) : h;
    if (out instanceof Response) return out;
    return new Response(out === undefined ? null : JSON.stringify(out), { status: out === undefined ? 204 : 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export const errorResponse = (status: number, detail: string) => new Response(JSON.stringify({ detail }), { status });

export function renderApp(path: string, token?: string) {
  if (token) localStorage.setItem("helpdesk.token", token);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

export async function axeViolations(container: Element) {
  // colour contrast needs real layout, which jsdom does not do; it is checked in a browser instead
  const r = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

export const session = {
  token: "t0k3n",
  workspace: "Demo University",
  user: { id: 1, name: "Demo Admin", email: "admin@helpdesk.example", role: "admin" as const },
};

export const kb = {
  id: 1,
  name: "Placement Cell help centre",
  slug: "placement-cell",
  description: "Demo articles",
  team_name: "a university Placement Cell",
  fallback_message: "I could not find this.",
  created_at: "2026-10-01T10:00:00Z",
  document_count: 20,
  chunk_count: 53,
  questions_7d: 9,
};
