import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth";
import { Loading } from "./Loading";

export function Brand() {
  return (
    <Link to="/" className="brand">
      <span className="logo" aria-hidden="true">
        ✦
      </span>
      HelpDesk AI
    </Link>
  );
}

// Signed-in area: top bar + page. Anyone not signed in is sent to the login page (and back afterwards).
export function AppLayout() {
  const { session, loading, signOut } = useAuth();
  const location = useLocation();
  if (loading) return <Loading label="Signing you in…" />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <>
      <header className="topbar">
        <div className="topbar-in">
          <Brand />
          <span className="workspace">{session.workspace}</span>
          <span className="spacer" />
          <span className="user">
            {session.user.name} <span className="role">{session.user.role}</span>
          </span>
          <button type="button" className="ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}

export function Tabs({ items }: { items: { to: string; label: string }[] }) {
  return (
    <nav className="tabs" aria-label="Knowledge base sections">
      {items.map((t) => (
        <NavLink key={t.to} to={t.to} end className={({ isActive }) => (isActive ? "tab active" : "tab")}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
