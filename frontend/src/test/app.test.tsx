import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Answer } from "../api";
import { ChatThread } from "../components/ChatThread";
import { Dropzone } from "../components/Dropzone";
import { axeViolations, errorResponse, kb, mockApi, renderApp, session } from "./helpers";
import { PublicChatPage } from "../pages/PublicChat";

afterEach(() => vi.unstubAllGlobals());

const answer = (over: Partial<Answer> = {}): Answer => ({
  conversation_id: 7,
  message_id: 11,
  text: "Once an interview is scheduled you cannot withdraw through the portal.",
  abstained: false,
  mode: "extractive",
  note: "",
  sources: [
    { source: "06-withdrawing#when-you-can-withdraw", title: "Withdrawing an application", section: "When you can withdraw", text: "You can withdraw while Applied or Shortlisted." },
    { source: "06-withdrawing#no-show-penalty", title: "Withdrawing an application", section: "No-show penalty", text: "Two no-shows suspend portal access for 30 days." },
  ],
  ...over,
});

describe("sign in", () => {
  it("signs in and shows the workspace's knowledge bases", async () => {
    const calls = mockApi({ "POST /api/auth/login": session, "GET /api/kbs": [kb] });
    renderApp("/login");
    await userEvent.type(screen.getByLabelText("Email"), "admin@helpdesk.example");
    await userEvent.type(screen.getByLabelText("Password"), "demo-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Placement Cell help centre" })).toBeInTheDocument();
    expect(localStorage.getItem("helpdesk.token")).toBe("t0k3n");
    const kbCall = calls.find((c) => c.url === "/api/kbs")!;
    expect(kbCall.headers.get("Authorization")).toBe("Bearer t0k3n");
  });

  it("shows the server's message when sign-in fails, and the page has no accessibility violations", async () => {
    mockApi({ "POST /api/auth/login": () => errorResponse(401, "wrong email or password") });
    const { container } = renderApp("/login");
    await userEvent.type(screen.getByLabelText("Email"), "a@b.example");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong email or password");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("sends signed-out visitors to the login page", async () => {
    mockApi({});
    renderApp("/kb/1/analytics");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("chat with citations", () => {
  it("shows the cited passage when a source is clicked, and continues the same conversation", async () => {
    const onAsk = vi.fn(async () => answer());
    const onFeedback = vi.fn(async () => {});
    const { container } = render(<ChatThread onAsk={onAsk} onFeedback={onFeedback} />);
    await userEvent.type(screen.getByLabelText("Your question"), "Can I withdraw after the interview is scheduled?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/cannot withdraw through the portal/)).toBeInTheDocument();
    const panel = screen.getByRole("complementary", { name: "Source passage" });
    expect(within(panel).getByText("You can withdraw while Applied or Shortlisted.")).toBeInTheDocument(); // first source opens by default

    await userEvent.click(screen.getByRole("button", { name: /No-show penalty/ }));
    expect(within(panel).getByText("Two no-shows suspend portal access for 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /No-show penalty/ })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    expect(onFeedback).toHaveBeenCalledWith(11, -1);

    await userEvent.type(screen.getByLabelText("Your question"), "And after that?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(onAsk).toHaveBeenLastCalledWith("And after that?", 7)); // follow-up keeps conversation 7
    expect(await axeViolations(container)).toEqual([]);
  });

  it("marks refusals and offers no feedback or sources for them", async () => {
    render(<ChatThread onAsk={async () => answer({ abstained: true, mode: "abstain", sources: [], text: "I could not find this." })} onFeedback={async () => {}} />);
    await userEvent.type(screen.getByLabelText("Your question"), "What is the hostel curfew?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Assistant · not in the documents")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Helpful" })).toBeNull();
  });

  it("asks the questions from a shareable link once, in order", async () => {
    const onAsk = vi.fn(async (q: string) => answer({ text: `answer to ${q}` }));
    render(<ChatThread onAsk={onAsk} initialQuestions={["first question", "second question"]} />);
    expect(await screen.findByText("answer to second question")).toBeInTheDocument();
    expect(onAsk.mock.calls.map((c) => c[0])).toEqual(["first question", "second question"]);
  });
});

describe("uploads", () => {
  it("rejects unsupported and oversized files before uploading", async () => {
    const onFiles = vi.fn();
    render(<Dropzone maxMb={1} onFiles={onFiles} />);
    const input = screen.getByLabelText("Upload documents");
    await userEvent.upload(input, new File(["MZ"], "setup.exe"), { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent("only PDF, Markdown and text");
    await userEvent.upload(input, new File([new Uint8Array(2 * 1024 * 1024)], "huge.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("larger than 1 MB");
    expect(onFiles).not.toHaveBeenCalled();
    const md = new File(["# Refunds"], "refunds.md");
    await userEvent.upload(input, md);
    expect(onFiles).toHaveBeenCalledWith([md]);
  });

  it("uploads a document and reports the new version from the server", async () => {
    const doc = { id: 3, filename: "refunds.md", doc_key: "refunds", title: "Refunds", kind: "markdown", size_bytes: 120, version: 2, chunk_count: 4, created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-02T10:00:00Z" };
    const calls = mockApi({
      "GET /api/auth/me": session,
      "GET /api/kbs/1": kb,
      "GET /api/kbs/1/settings": { max_upload_mb: 5 },
      "GET /api/kbs/1/documents": [doc],
      "POST /api/kbs/1/documents": doc,
    });
    renderApp("/kb/1/documents", "t0k3n");
    await userEvent.upload(await screen.findByLabelText("Upload documents"), new File(["# Refunds"], "refunds.md"));
    expect(await screen.findByText("Version 2 · 4 passages")).toBeInTheDocument();
    const up = calls.find((c) => c.method === "POST")!;
    expect(up.body).toBeInstanceOf(FormData);
    expect(up.headers.get("Content-Type")).toBeNull(); // the browser sets the multipart boundary itself
  });
});

describe("analytics", () => {
  it("shows totals, gaps and low-rated answers", async () => {
    mockApi({
      "GET /api/auth/me": session,
      "GET /api/kbs/1": kb,
      "GET /api/kbs/1/analytics": {
        days: 14,
        questions: 16,
        answered: 12,
        refused: 4,
        refusal_rate: 0.25,
        feedback: { up: 4, down: 2 },
        modes: { extractive: 12, abstain: 4 },
        latency_ms: { p50: null, p95: null },
        series: [
          { date: "2026-10-24", questions: 3, refused: 1 },
          { date: "2026-10-25", questions: 2, refused: 0 },
        ],
        gaps: [{ topic: "hostel", count: 2, examples: ["What is the hostel curfew?"] }],
        low_rated: [{ message_id: 5, question: "When do offer letters arrive?", answer: "…", sources: ["12-offer-letters#when"], comment: "Too vague", at: "2026-10-20T10:00:00Z" }],
      },
    });
    const { container } = renderApp("/kb/1/analytics", "t0k3n");
    expect(await screen.findByText("25%")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument(); // 4 of 6 ratings helpful
    expect(screen.getAllByText("–").length).toBeGreaterThan(0); // no latency measured: shown as a dash, not 0
    expect(screen.getByText("hostel")).toBeInTheDocument();
    expect(screen.getByText("“Too vague”")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Questions per day/ })).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("public widget", () => {
  function renderPublic(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/chat/:slug" element={<PublicChatPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("asks with the publishable key and never sends a session token", async () => {
    localStorage.setItem("helpdesk.token", "admin-session-token");
    const calls = mockApi({
      "GET /api/public/kbs/placement-cell": { name: "Placement Cell help centre", description: "Ask us", team_name: "x" },
      "POST /api/public/kbs/placement-cell/ask": answer(),
    });
    renderPublic("/chat/placement-cell?key=hd_demo&q=Can+I+withdraw%3F");
    expect(await screen.findByText(/cannot withdraw through the portal/)).toBeInTheDocument();
    for (const c of calls) {
      expect(c.headers.get("X-API-Key")).toBe("hd_demo");
      expect(c.headers.get("Authorization")).toBeNull();
    }
  });

  it("explains when the key is wrong", async () => {
    mockApi({ "GET /api/public/kbs/placement-cell": () => errorResponse(401, "invalid or revoked API key") });
    renderPublic("/chat/placement-cell?key=bad");
    expect(await screen.findByText("This assistant is not available")).toBeInTheDocument();
    expect(screen.getByText(/invalid or revoked API key/)).toBeInTheDocument();
  });
});
