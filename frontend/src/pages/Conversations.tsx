import { useEffect, useState } from "react";
import { api, citeLabel, formatDate, type ConversationRow } from "../api";
import { useLoad } from "../components/useLoad";
import { useKb } from "./KbShell";

export function ConversationsPage() {
  const { kb } = useKb();
  const [problems, setProblems] = useState(false);
  const { data, error } = useLoad(() => api.conversations(kb.id, problems), [kb.id, problems]);
  const [open, setOpen] = useState<ConversationRow | null>(null);
  // open the newest conversation by default, so the page never starts with an empty reading pane
  useEffect(() => {
    if (data && (!open || !data.some((c) => c.id === open.id))) setOpen(data[0] ?? null);
  }, [data, open]);
  const messages = useLoad(() => (open ? api.conversation(open.id) : Promise.resolve([])), [open?.id]);

  return (
    <div className="two-col">
      <div>
        <div className="toolbar">
          <label className="check">
            <input type="checkbox" checked={problems} onChange={(e) => setProblems(e.target.checked)} /> Only conversations with a refusal or a
            thumbs-down
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <ul className="conv-list">
          {data?.map((c) => (
            <li key={c.id}>
              <button type="button" className={`conv${open?.id === c.id ? " active" : ""}`} onClick={() => setOpen(c)}>
                <span className="conv-q">{c.first_question || "(no question)"}</span>
                <span className="conv-meta">
                  {formatDate(c.created_at)} · {c.channel === "public" ? "Public widget" : "Console"} · {c.messages / 2} question
                  {c.messages === 2 ? "" : "s"}
                  {c.refused > 0 && <span className="pill warn">{c.refused} refused</span>}
                  {c.rating_down > 0 && <span className="pill bad">👎 {c.rating_down}</span>}
                  {c.is_demo && <span className="pill demo">demo</span>}
                </span>
              </button>
            </li>
          ))}
          {data?.length === 0 && <li className="muted">No conversations yet.</li>}
        </ul>
      </div>
      <aside className="card preview" aria-label="Conversation">
        {!open && <p className="muted">Select a conversation to read it.</p>}
        {open && (
          <>
            <h2>Conversation #{open.id}</h2>
            {open.is_demo && <p className="note small">Sample data created by the demo seed script; ratings on it are invented.</p>}
            {messages.data?.map((m) => (
              <div key={m.id} className={`msg ${m.role === "user" ? "me" : "bot"}${m.abstained ? " refused" : ""}`}>
                <span className="who">
                  {m.role === "user" ? "Customer" : "Assistant"}
                  {m.rating === 1 && " · 👍"}
                  {m.rating === -1 && " · 👎"}
                </span>
                {m.text}
                {m.sources && m.sources.length > 0 && <p className="small muted">Sources: {m.sources.map(citeLabel).join("; ")}</p>}
              </div>
            ))}
          </>
        )}
      </aside>
    </div>
  );
}
