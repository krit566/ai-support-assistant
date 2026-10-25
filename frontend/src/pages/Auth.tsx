import { useId, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { Brand } from "../components/Layout";

function Field(props: { label: string; type?: string; value: string; onChange: (v: string) => void; autoComplete: string; minLength?: number }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      <input
        id={id}
        type={props.type ?? "text"}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        autoComplete={props.autoComplete}
        minLength={props.minLength}
        required
      />
    </div>
  );
}

function AuthFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-hero">
        <Brand />
        <h1>Answers from your documents. With sources. Or an honest “I don’t know”.</h1>
        <ul>
          <li>Upload PDFs, Markdown or text; every answer cites the passage it came from</li>
          <li>Refuses when the documents do not cover a question, instead of guessing</li>
          <li>See what customers ask, what was refused and which answers they disliked</li>
        </ul>
      </div>
      <main className="auth-card card">
        <h2>{title}</h2>
        {children}
      </main>
    </div>
  );
}

export function LoginPage() {
  const { session, signIn } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (session) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      signIn(await api.login(email, password));
      nav(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Sign in">
      <form onSubmit={submit}>
        <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary wide" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="muted small">
        New team? <Link to="/signup">Create a workspace</Link>
      </p>
    </AuthFrame>
  );
}

export function SignupPage() {
  const { session, signIn } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ workspace: "", name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (session) return <Navigate to="/" replace />;
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      signIn(await api.signup(f));
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the workspace");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Create a workspace">
      <form onSubmit={submit}>
        <Field label="Team or company" value={f.workspace} onChange={set("workspace")} autoComplete="organization" />
        <Field label="Your name" value={f.name} onChange={set("name")} autoComplete="name" />
        <Field label="Email" type="email" value={f.email} onChange={set("email")} autoComplete="email" />
        <Field label="Password (10+ characters)" type="password" value={f.password} onChange={set("password")} autoComplete="new-password" minLength={10} />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary wide" disabled={busy}>
          {busy ? "Creating…" : "Create workspace"}
        </button>
      </form>
      <p className="muted small">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthFrame>
  );
}
