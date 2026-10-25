// The page customers see: /chat/<knowledge base>?key=<publishable key>. No sign-in.

import { useParams, useSearchParams } from "react-router";
import { api } from "../api";
import { ChatThread } from "../components/ChatThread";
import { useLoad } from "../components/useLoad";

export function PublicChatPage() {
  const slug = useParams().slug ?? "";
  const [params] = useSearchParams();
  const key = params.get("key") ?? "";
  const info = useLoad(() => api.publicKb(slug, key), [slug, key]);

  return (
    <div className="public">
      <header className="public-hero">
        <div className="public-in">
          <span className="badge">Answers cite their sources · says so when it doesn’t know</span>
          <h1>{info.data?.name ?? "Help assistant"}</h1>
          <p>{info.data?.description}</p>
        </div>
      </header>
      <main className="public-main">
        {info.error ? (
          <div className="card">
            <h2>This assistant is not available</h2>
            <p className="muted">{info.error}. Check the link you were given.</p>
          </div>
        ) : (
          <ChatThread
            onAsk={(q, conv) => api.publicAsk(slug, key, q, conv)}
            onFeedback={(m, r) => api.publicFeedback(slug, key, m, r)}
            placeholder="Type your question…"
            initialQuestions={params.getAll("q")}
          />
        )}
        <p className="muted small center">Powered by HelpDesk AI</p>
      </main>
    </div>
  );
}
