import { useId, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { Loading } from "../components/Loading";
import { useLoad } from "../components/useLoad";

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);

export function KbListPage() {
  const { session } = useAuth();
  const { data, error, loading } = useLoad(api.kbs, []);
  const [creating, setCreating] = useState(false);
  const isAdmin = session?.user.role === "admin";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Knowledge bases</h1>
          <p className="muted">Each knowledge base is a set of documents with its own assistant, public widget and analytics.</p>
        </div>
        {isAdmin && !creating && (
          <button className="primary" onClick={() => setCreating(true)}>
            New knowledge base
          </button>
        )}
      </div>
      {creating && <CreateKb onCancel={() => setCreating(false)} />}
      {loading && <Loading />}
      {error && <p className="error">{error}</p>}
      {data && data.length === 0 && !creating && (
        <div className="card empty-state">
          <h2>No knowledge bases yet</h2>
          <p className="muted">{isAdmin ? "Create one and upload your help articles, policies or FAQs." : "Ask an admin to create one."}</p>
        </div>
      )}
      <div className="grid">
        {data?.map((kb) => (
          <Link key={kb.id} to={`/kb/${kb.id}`} className="card kb-card">
            <h2>{kb.name}</h2>
            <p className="muted small">{kb.description || "No description"}</p>
            <div className="kb-stats">
              <span>
                <b>{kb.document_count}</b> documents
              </span>
              <span>
                <b>{kb.chunk_count}</b> passages
              </span>
              <span>
                <b>{kb.questions_7d}</b> questions this week
              </span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

function CreateKb({ onCancel }: { onCancel: () => void }) {
  const nav = useNavigate();
  const ids = { name: useId(), slug: useId(), team: useId(), desc: useId(), fb: useId() };
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [team, setTeam] = useState("the support team");
  const [description, setDescription] = useState("");
  const [fallback, setFallback] = useState("I could not find this in our help centre. Please contact the support team.");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const kb = await api.createKb({ name, slug: slug || slugify(name), description, team_name: team, fallback_message: fallback });
      nav(`/kb/${kb.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create");
    }
  }

  return (
    <form className="card form-grid" onSubmit={submit}>
      <h2>New knowledge base</h2>
      <div className="field">
        <label htmlFor={ids.name}>Name</label>
        <input id={ids.name} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
      </div>
      <div className="field">
        <label htmlFor={ids.slug}>Public address</label>
        <input id={ids.slug} value={slug} placeholder={slugify(name) || "my-help-centre"} onChange={(e) => setSlug(slugify(e.target.value))} />
        <small className="muted">The public chat page will be /chat/{slug || slugify(name) || "…"}</small>
      </div>
      <div className="field">
        <label htmlFor={ids.team}>The assistant speaks for</label>
        <input id={ids.team} value={team} onChange={(e) => setTeam(e.target.value)} required minLength={2} />
      </div>
      <div className="field">
        <label htmlFor={ids.desc}>Description</label>
        <input id={ids.desc} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="field span">
        <label htmlFor={ids.fb}>Message when the documents do not cover a question</label>
        <input id={ids.fb} value={fallback} onChange={(e) => setFallback(e.target.value)} required minLength={10} />
      </div>
      {error && (
        <p className="error span" role="alert">
          {error}
        </p>
      )}
      <div className="actions span">
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
        <button className="primary">Create</button>
      </div>
    </form>
  );
}
