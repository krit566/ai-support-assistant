import { useState } from "react";
import { api, formatBytes, formatDate, type ChunkRow, type Doc } from "../api";
import { useAuth } from "../auth";
import { Dropzone } from "../components/Dropzone";
import { useLoad } from "../components/useLoad";
import { useKb } from "./KbShell";

interface UploadState {
  name: string;
  status: "uploading" | "done" | "failed";
  message: string;
}

const KIND: Record<Doc["kind"], string> = { pdf: "PDF", markdown: "MD", text: "TXT" };

export function DocumentsPage() {
  const { kb, reloadKb } = useKb();
  const { session } = useAuth();
  const isAdmin = session?.user.role === "admin";
  const { data: docs, error, reload } = useLoad(() => api.documents(kb.id), [kb.id]);
  const settings = useLoad(() => api.settings(kb.id), [kb.id]);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [preview, setPreview] = useState<{ doc: Doc; chunks: ChunkRow[] } | null>(null);
  const [busyDoc, setBusyDoc] = useState<number | null>(null);

  async function uploadAll(files: File[]) {
    setUploads(files.map((f) => ({ name: f.name, status: "uploading", message: "Uploading and indexing…" })));
    for (const [i, f] of files.entries()) {
      try {
        const d = await api.upload(kb.id, f);
        const message = d.version > 1 ? `Version ${d.version} · ${d.chunk_count} passages` : `${d.chunk_count} passages indexed`;
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, status: "done", message } : x)));
      } catch (e) {
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, status: "failed", message: e instanceof Error ? e.message : "Failed" } : x)));
      }
    }
    reload();
    reloadKb();
  }

  async function act(doc: Doc, what: "reindex" | "delete") {
    if (what === "delete" && !window.confirm(`Delete “${doc.filename}”? The assistant will stop using it immediately.`)) return;
    setBusyDoc(doc.id);
    try {
      if (what === "delete") await api.deleteDoc(doc.id);
      else await api.reindex(doc.id);
      if (preview?.doc.id === doc.id) setPreview(null);
      reload();
      reloadKb();
    } finally {
      setBusyDoc(null);
    }
  }

  async function show(doc: Doc) {
    setPreview({ doc, chunks: await api.chunks(doc.id) });
  }

  return (
    <div className="two-col">
      <div>
        {isAdmin && <Dropzone maxMb={settings.data?.max_upload_mb ?? 5} onFiles={uploadAll} />}
        {uploads.length > 0 && (
          <ul className="uploads" aria-live="polite">
            {uploads.map((u) => (
              <li key={u.name} className={u.status}>
                <span className="name">{u.name}</span> <span className="small">{u.message}</span>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="error">{error}</p>}
        <div className="card table-card">
          <table className="table">
            <caption className="sr-only">Documents</caption>
            <thead>
              <tr>
                <th>Document</th>
                <th className="hide-sm">Type</th>
                <th>Passages</th>
                <th className="hide-sm">Version</th>
                <th className="hide-sm">Updated</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {docs?.map((d) => (
                <tr key={d.id} className={preview?.doc.id === d.id ? "selected" : ""}>
                  <td>
                    <button type="button" className="link strong" onClick={() => show(d)}>
                      {d.title}
                    </button>
                    <div className="muted small">
                      {d.filename} · {formatBytes(d.size_bytes)}
                    </div>
                  </td>
                  <td className="hide-sm">
                    <span className={`kind kind-${d.kind}`}>{KIND[d.kind]}</span>
                  </td>
                  <td>
                    <span className="indexed">● {d.chunk_count}</span>
                  </td>
                  <td className="hide-sm">v{d.version}</td>
                  <td className="small hide-sm">{formatDate(d.updated_at)}</td>
                  <td className="row-actions">
                    {isAdmin && (
                      <>
                        <button type="button" className="secondary small-btn" disabled={busyDoc === d.id} onClick={() => act(d, "reindex")}>
                          Re-index
                        </button>
                        <button type="button" className="danger small-btn" disabled={busyDoc === d.id} onClick={() => act(d, "delete")}>
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {docs?.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted center">
                    No documents yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <aside className="card preview" aria-label="Passages">
        {preview ? (
          <>
            <h2>{preview.doc.title}</h2>
            <p className="muted small">
              {preview.chunks.length} passages · citation id <code>{preview.doc.doc_key}</code>
            </p>
            <ol className="chunks">
              {preview.chunks.map((c) => (
                <li key={c.id}>
                  <p className="chunk-section">{c.section}</p>
                  <p>{c.text}</p>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <>
            <h2>Passages</h2>
            <p className="muted">
              Each document is split into passages: Markdown by its “##” sections, PDFs by page, text files by paragraphs. Select a document to
              see exactly what the assistant can quote.
            </p>
          </>
        )}
      </aside>
    </div>
  );
}
