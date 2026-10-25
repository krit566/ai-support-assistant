import { useSearchParams } from "react-router";
import { api } from "../api";
import { ChatThread } from "../components/ChatThread";
import { useKb } from "./KbShell";

export function PlaygroundPage() {
  const { kb } = useKb();
  const initial = useSearchParams()[0].getAll("q");
  const examples =
    kb.slug === "placement-cell"
      ? ["Can I withdraw after my interview is scheduled?", "I got a job outside campus, what do I do?", "What is the hostel curfew?"]
      : [];
  return (
    <>
      <p className="muted intro">
        Test the assistant exactly as customers will see it. Answers come only from this knowledge base’s documents; questions here are saved
        under Conversations.
      </p>
      <ChatThread
        key={kb.id}
        onAsk={(q, conv) => api.ask(kb.id, q, conv)}
        onFeedback={(m, r) => api.feedback(m, r)}
        examples={examples}
        initialQuestions={initial}
        emptyText={kb.document_count ? undefined : "This knowledge base has no documents yet: upload some under Documents first."}
      />
    </>
  );
}
