import { useId, useState, type FormEvent } from "react";
import { api, formatDate, type KeyRow } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../components/useLoad";
import { useKb } from "./KbShell";

export function SettingsPage() {
  const { kb, reloadKb } = useKb();
  const { session } = useAuth();
  const isAdmin = session?.user.role === "admin";
  const s = useLoad(() => api.settings(kb.id), [kb.id]);
  const keys = useLoad(() => (isAdmin ? api.keys(kb.id) : Promise.resolve([] as KeyRow[])), [kb.id, isAdmin]);
  const [created, setCreated] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("Website widget");
  const [rate, setRate] = useState(20);
  const [fallback, setFallback] = useState(kb.fallback_message);
  const [team, setTeam] = useState(kb.team_name);
  const [saved, setSaved] = useState("");
  const ids = { fb: useId(), team: useId(), kn: useId(), rate: useId() };

  async function saveKb(e: FormEvent) {
    e.preventDefault();
    await api.updateKb(kb.id, { fallback_message: fallback, team_name: team });
    setSaved("Saved");
    reloadKb();
  }

  async function newKey(e: FormEvent) {
    e.preventDefault();
    const k = await api.createKey(kb.id, keyName, rate);
    setCreated(k.key);
    keys.reload();
  }

  const widgetUrl = created ? `${location.origin}/chat/${kb.slug}?key=${created}` : "";

  return (
    <div className="settings">
      <section className="card">
        <h2>How this assistant answers</h2>
        {s.data && (
          <dl className="facts">
            <dt>Retrieval</dt>
            <dd>{s.data.retrieval}</dd>
            <dt>Embeddings</dt>
            <dd>
              <code>{s.data.embedder}</code>
            </dd>
            <dt>Refuse when</dt>
            <dd>
              best passage has cosine &lt; {s.data.thresholds.min_dense} <b>and</b> BM25 &lt; {s.data.thresholds.min_bm25.toFixed(2)}
            </dd>
            <dt>Where the thresholds come from</dt>
            <dd>{s.data.thresholds_source}. The BM25 threshold is rescaled for this knowledge base’s size.</dd>
            <dt>Answer style</dt>
            <dd>{s.data.llm_answers ? "LLM, allowed to cite only the passages it was given" : "Extractive: quoted sentences from the best passages"}</dd>
          </dl>
        )}
      </section>

      {isAdmin && (
        <form className="card" onSubmit={saveKb}>
          <h2>Wording</h2>
          <div className="field">
            <label htmlFor={ids.team}>The assistant speaks for</label>
            <input id={ids.team} value={team} onChange={(e) => setTeam(e.target.value)} minLength={2} required />
          </div>
          <div className="field">
            <label htmlFor={ids.fb}>Message when the documents do not cover a question</label>
            <textarea id={ids.fb} value={fallback} onChange={(e) => setFallback(e.target.value)} minLength={10} required rows={3} />
          </div>
          <button className="primary">Save</button> <span className="muted small" role="status">{saved}</span>
        </form>
      )}

      {isAdmin && (
        <section className="card">
          <h2>Public widget keys</h2>
          <p className="muted small">
            A key lets a public page ask questions of this knowledge base, and nothing else. It is visible to visitors, so each key is
            rate-limited and can be revoked.
          </p>
          <form className="inline-form" onSubmit={newKey}>
            <div className="field">
              <label htmlFor={ids.kn}>Name</label>
              <input id={ids.kn} value={keyName} onChange={(e) => setKeyName(e.target.value)} minLength={2} required />
            </div>
            <div className="field narrow">
              <label htmlFor={ids.rate}>Questions per minute</label>
              <input id={ids.rate} type="number" min={1} max={600} value={rate} onChange={(e) => setRate(Number(e.target.value))} />
            </div>
            <button className="primary">Create key</button>
          </form>
          {created && (
            <div className="note" role="status">
              <p className="strong">Copy this key now: it is shown only once.</p>
              <code className="secret">{created}</code>
              <p className="small">
                Public chat page: <a href={widgetUrl}>{widgetUrl}</a>
              </p>
            </div>
          )}
          <table className="table">
            <caption className="sr-only">API keys</caption>
            <thead>
              <tr>
                <th>Name</th>
                <th>Key</th>
                <th className="hide-sm">Limit</th>
                <th className="hide-sm">Last used</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {keys.data?.map((k) => (
                <tr key={k.id} className={k.revoked_at ? "revoked" : ""}>
                  <td>{k.name}</td>
                  <td>
                    <code>{k.prefix}…</code>
                  </td>
                  <td className="hide-sm">{k.rate_per_minute}/min</td>
                  <td className="small hide-sm">{k.last_used_at ? formatDate(k.last_used_at) : "never"}</td>
                  <td>
                    {k.revoked_at ? (
                      <span className="pill">revoked</span>
                    ) : (
                      <button
                        type="button"
                        className="danger small-btn"
                        onClick={async () => {
                          await api.revokeKey(kb.id, k.id);
                          keys.reload();
                        }}
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
