// A conversation: question bubbles, answers with citation chips, thumbs up/down, and a source panel.
// Used by the admin playground and by the public widget (they differ only in how they call the API).

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { citeLabel, type Answer, type Passage } from "../api";

export interface Turn {
  question: string;
  answer?: Answer;
  error?: string;
  rating?: 1 | -1;
}

interface Props {
  onAsk: (question: string, conversationId?: number) => Promise<Answer>;
  onFeedback?: (messageId: number, rating: 1 | -1) => Promise<void>;
  examples?: string[];
  placeholder?: string;
  emptyText?: string;
  initialQuestions?: string[]; // asked in order when the page opens (shareable links: ?q=...&q=...)
}

export function ChatThread({ onAsk, onFeedback, examples = [], placeholder = "Ask a question…", emptyText, initialQuestions = [] }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Passage | null>(null);
  const conversationId = useRef<number | undefined>(undefined);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputId = useId();

  useEffect(() => {
    // scroll only the conversation box (scrollIntoView would also scroll the whole page)
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || initialQuestions.length === 0) return;
    asked.current = true; // once, even though React runs effects twice in development
    void (async () => {
      for (const q of initialQuestions) await ask(q);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const inFlight = useRef(false);

  async function ask(q: string) {
    const text = q.trim();
    if (text.length < 3 || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setQuestion("");
    setTurns((t) => [...t, { question: text }]);
    try {
      const a = await onAsk(text, conversationId.current);
      conversationId.current = a.conversation_id; // follow-up questions stay in the same conversation
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer: a } : turn)));
      if (a.sources[0]) setOpen(a.sources[0]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Something went wrong";
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: msg } : turn)));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function rate(index: number, rating: 1 | -1) {
    const msg = turns[index].answer?.message_id;
    if (!msg || !onFeedback) return;
    setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, rating } : turn)));
    try {
      await onFeedback(msg, rating);
    } catch {
      setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, rating: undefined } : turn)));
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <div className="chat-layout">
      <section className="card chat" aria-label="Conversation">
        <div className="thread" aria-live="polite" ref={threadRef}>
          {turns.length === 0 && <p className="empty">{emptyText ?? "Ask anything covered by the documents in this knowledge base."}</p>}
          {turns.map((t, i) => (
            <div key={i} className="turn">
              <div className="msg me">
                <span className="who">You</span>
                {t.question}
              </div>
              {!t.answer && !t.error && (
                <div className="msg bot pending" role="status">
                  <span className="who">Assistant</span>Searching the documents…
                </div>
              )}
              {t.error && (
                <div className="msg bot refused" role="alert">
                  <span className="who">Assistant</span>
                  {t.error}
                </div>
              )}
              {t.answer && (
                <div className={`msg bot${t.answer.abstained ? " refused" : ""}`}>
                  <span className="who">{t.answer.abstained ? "Assistant · not in the documents" : "Assistant"}</span>
                  {t.answer.text}
                  {t.answer.sources.length > 0 && (
                    <ul className="cites" aria-label="Sources">
                      {t.answer.sources.map((s, j) => (
                        <li key={s.source}>
                          <button
                            type="button"
                            className={`cite${open?.source === s.source ? " active" : ""}`}
                            onClick={() => setOpen(s)}
                            aria-pressed={open?.source === s.source}
                          >
                            <span className="cite-n">{j + 1}</span>
                            {citeLabel(s)}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {onFeedback && !t.answer.abstained && (
                    <div className="rate" role="group" aria-label="Was this helpful?">
                      <button type="button" className="icon" aria-pressed={t.rating === 1} onClick={() => rate(i, 1)} title="Helpful">
                        <span aria-hidden="true">👍</span>
                        <span className="sr-only">Helpful</span>
                      </button>
                      <button type="button" className="icon" aria-pressed={t.rating === -1} onClick={() => rate(i, -1)} title="Not helpful">
                        <span aria-hidden="true">👎</span>
                        <span className="sr-only">Not helpful</span>
                      </button>
                      {t.rating && <span className="muted small">Thanks for the feedback</span>}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        <form className="ask" onSubmit={submit}>
          <label htmlFor={inputId} className="sr-only">
            Your question
          </label>
          <input
            id={inputId}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={500}
            autoComplete="off"
            placeholder={placeholder}
            disabled={busy}
          />
          <button type="submit" className="primary" disabled={busy || question.trim().length < 3}>
            Ask
          </button>
        </form>
        {examples.length > 0 && (
          <div className="chips" aria-label="Example questions">
            {examples.map((x) => (
              <button key={x} type="button" className="chip" onClick={() => ask(x)} disabled={busy}>
                {x}
              </button>
            ))}
          </div>
        )}
      </section>
      <aside className="card source-panel" aria-label="Source passage">
        <h2>Source</h2>
        {open ? (
          <>
            <p className="source-title">{open.title}</p>
            <p className="muted small">
              {open.section} · <code>{open.source}</code>
            </p>
            <blockquote>{open.text}</blockquote>
            <p className="muted small">This is the exact passage the answer was taken from.</p>
          </>
        ) : (
          <p className="muted">Click a source under an answer to read the passage it came from.</p>
        )}
      </aside>
    </div>
  );
}
