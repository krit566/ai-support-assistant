"""Evaluate retrieval, abstention and answers on the question set.

    python eval/run_eval.py                    # LSA embedder, extractive answers (offline)
    python eval/run_eval.py --embedder sbert   # pretrained embeddings (pip install sentence-transformers)
    python eval/run_eval.py --llm              # LLM answers too (needs GROQ_API_KEY or LLM_API_KEY)

1. Thresholds for "I don't know" are chosen on the DEV split only and saved to eval/thresholds.json.
2. Everything reported is measured on the TEST split, which the thresholds never saw.

Metrics (test split):
  recall@k         the right article is among the top k retrieved (answerable questions)
  MRR              mean of 1/rank of the right article
  abstention       unanswerable questions correctly refused / answerable questions wrongly refused
  answer accuracy  answer cites the right article AND contains the key fact (answerable, not refused)

CAVEAT: the articles and the questions were written by the same person, so scores are optimistic. Questions are
paraphrased on purpose (e.g. "uncleared subject" for "backlog") to make keyword matching harder.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistant.answer import answer  # noqa: E402
from assistant.chunking import load_corpus  # noqa: E402
from assistant.core import DOCS, THRESHOLDS  # noqa: E402
from assistant.embeddings import make_embedder  # noqa: E402
from assistant.retriever import Retriever, should_abstain  # noqa: E402

METHODS = ["bm25", "dense", "hybrid"]


def load_questions() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def retrieval_metrics(r: Retriever, qs: list[dict], method: str) -> dict:
    ans = [q for q in qs if q["doc"]]
    r1 = r3 = mrr = 0.0
    for q in ans:
        ranked = r.docs_ranked(q["question"], k=10, method=method)
        if ranked[:1] == [q["doc"]]:
            r1 += 1
        if q["doc"] in ranked[:3]:
            r3 += 1
        if q["doc"] in ranked:
            mrr += 1 / (ranked.index(q["doc"]) + 1)
    n = len(ans)
    return {"recall@1": round(r1 / n, 3), "recall@3": round(r3 / n, 3), "MRR": round(mrr / n, 3), "n": n}


def tune_thresholds(r: Retriever, dev: list[dict]) -> dict:
    """Grid search on DEV: maximise (answerable answered) + (unanswerable refused), prefer refusing less on ties."""
    tops = [(q, r.search(q["question"], k=1)[0]) for q in dev]
    best, best_key = None, None
    for d, b in itertools.product([x / 100 for x in range(0, 100, 2)], [x / 2 for x in range(0, 31)]):
        good = sum((q["doc"] is None) == should_abstain([h], d, b) for q, h in tops)
        refused_answerable = sum(1 for q, h in tops if q["doc"] and should_abstain([h], d, b))
        key = (good, -refused_answerable, -d, -b)
        if best_key is None or key > best_key:
            best, best_key = {"min_dense": d, "min_bm25": b}, key
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", default="lsa", choices=["lsa", "sbert", "api"])
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()

    chunks = load_corpus(DOCS)
    emb = make_embedder(a.embedder, [c.for_index() for c in chunks])
    r = Retriever(chunks, emb)
    qs = load_questions()
    dev, test = [q for q in qs if q["split"] == "dev"], [q for q in qs if q["split"] == "test"]

    th = tune_thresholds(r, dev)
    saved = json.loads(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}
    saved[emb.name] = th
    THRESHOLDS.write_text(json.dumps(saved, indent=1), encoding="utf-8")

    report = {
        "embedder": emb.name,
        "chunks": len(chunks),
        "articles": len({c.doc for c in chunks}),
        "questions": {"dev": len(dev), "test": len(test)},
        "thresholds_from_dev": th,
        "retrieval_test": {m: retrieval_metrics(r, test, m) for m in METHODS},
    }

    modes = ["extractive"] + (["llm"] if a.llm else [])
    for mode in modes:
        refused_ok = refused_wrong = correct = answered = 0
        misses = []
        for q in test:
            hits = r.search(q["question"], k=5, method="hybrid")
            abstain = should_abstain(hits, **th)
            ans = answer(q["question"], hits, abstain, use_llm=(mode == "llm"), idf=r.bm25.idf)
            if q["doc"] is None:
                refused_ok += ans.abstained
                if not ans.abstained:
                    misses.append({"id": q["id"], "why": "answered an unanswerable question", "sources": ans.sources})
                continue
            if ans.abstained:
                refused_wrong += 1
                misses.append({"id": q["id"], "why": "refused an answerable question"})
                continue
            answered += 1
            cites = any(s.startswith(q["doc"] + "#") for s in ans.sources)
            has_fact = q["fact"].lower() in ans.text.lower()
            if cites and has_fact:
                correct += 1
            else:
                misses.append({"id": q["id"], "why": ("wrong source" if not cites else "key fact missing"), "sources": ans.sources})
        n_ans = sum(1 for q in test if q["doc"])
        n_un = len(test) - n_ans
        report[f"answers_test_{mode}"] = {
            "answer_accuracy": round(correct / n_ans, 3),
            "correct": correct,
            "answerable": n_ans,
            "unanswerable_refused": f"{refused_ok}/{n_un}",
            "answerable_wrongly_refused": f"{refused_wrong}/{n_ans}",
            "misses": misses,
        }

    out = ROOT / "eval" / f"results_{emb.name.replace(':', '_')}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
