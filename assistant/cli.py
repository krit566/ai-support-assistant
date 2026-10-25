"""Ask from the terminal.

    python -m assistant.cli "Can I withdraw after my interview is scheduled?"
    python -m assistant.cli --llm "..."            # needs GROQ_API_KEY (or LLM_API_KEY)
    python -m assistant.cli                        # interactive
"""

from __future__ import annotations

import argparse

from .core import Assistant


def show(a) -> None:
    print("\n" + a.text)
    if a.sources:
        print("Sources: " + ", ".join(a.sources))
    print(f"[{a.mode}{'; ' + a.note if a.note else ''}]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--embedder", choices=["lsa", "sbert", "api"])
    a = ap.parse_args()
    bot = Assistant(embedder=a.embedder, use_llm=a.llm)
    if a.question:
        show(bot.ask(" ".join(a.question)))
        return
    print("Ask a question (empty line to quit).")
    while q := input("> ").strip():
        show(bot.ask(q))


if __name__ == "__main__":
    main()
