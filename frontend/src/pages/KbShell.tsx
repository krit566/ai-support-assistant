import { Link, Outlet, useOutletContext, useParams } from "react-router";
import { api, type Kb } from "../api";
import { Tabs } from "../components/Layout";
import { Loading } from "../components/Loading";
import { useLoad } from "../components/useLoad";

export interface KbContext {
  kb: Kb;
  reloadKb: () => void;
}

export const useKb = () => useOutletContext<KbContext>();

// Header and tabs shared by every page of one knowledge base
export function KbShell() {
  const id = Number(useParams().kbId);
  const { data: kb, error, reload } = useLoad(() => api.kb(id), [id]);
  if (error) return <p className="error">{error}</p>;
  if (!kb) return <Loading />;
  const base = `/kb/${kb.id}`;
  return (
    <>
      <p className="crumbs">
        <Link to="/">Knowledge bases</Link> › {kb.name}
      </p>
      <div className="page-head">
        <div>
          <h1>{kb.name}</h1>
          <p className="muted">
            {kb.document_count} documents · {kb.chunk_count} passages · public page <code>/chat/{kb.slug}</code>
          </p>
        </div>
      </div>
      <Tabs
        items={[
          { to: base, label: "Playground" },
          { to: `${base}/documents`, label: "Documents" },
          { to: `${base}/conversations`, label: "Conversations" },
          { to: `${base}/analytics`, label: "Analytics" },
          { to: `${base}/settings`, label: "Settings" },
        ]}
      />
      <Outlet context={{ kb, reloadKb: reload } satisfies KbContext} />
    </>
  );
}
