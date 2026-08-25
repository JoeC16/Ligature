"""Text-to-Cypher NL query layer (build order step 5). Prototyped standalone
per CLAUDE.md ("can be prototyped standalone before full integration"),
then wired into api/app.py's POST /ask in step 7 — ask() below is the
shared pipeline both this CLI and that endpoint call.

Usage:
    python nl_query/ask.py "which injuries have no treatment logged yet?"

Pipeline: translate the question to Cypher (refusing rather than guessing
if the schema can't answer it) -> reject anything that isn't read-only ->
run it in a Neo4j read transaction -> explain the exact results in plain
language -> print the answer plus the underlying query and raw rows, so
every answer is directly verifiable against the graph.

Requires ANTHROPIC_API_KEY in .env (same pattern as the NEO4J_* vars).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

NL_QUERY_DIR = Path(__file__).resolve().parent
REPO_ROOT = NL_QUERY_DIR.parent
sys.path.insert(0, str(NL_QUERY_DIR))
sys.path.insert(0, str(REPO_ROOT))

import anthropic  # noqa: E402

from common import db  # noqa: E402
from executor import run_read_only  # noqa: E402
from guard import UnsafeQueryError, check_read_only  # noqa: E402
from responder import explain  # noqa: E402
from translator import translate  # noqa: E402


def ask(client, session, question: str) -> dict:
    """Runs the full translate -> guard -> execute -> explain pipeline and
    returns a structured result instead of printing, so callers other than
    the CLI (namely api/app.py's POST /ask) can get JSON back directly
    rather than parsing stdout. `status` is one of "ok", "refused", "unsafe",
    or "error" — exactly one of the other keys is populated accordingly.
    """
    translation = translate(client, question)
    if translation.cypher is None:
        return {"status": "refused", "question": question, "refusal_reason": translation.refusal_reason}

    try:
        check_read_only(translation.cypher)
    except UnsafeQueryError as e:
        return {"status": "unsafe", "question": question, "cypher": translation.cypher, "reason": str(e)}

    try:
        rows = run_read_only(session, translation.cypher)
    except Exception as e:
        return {"status": "error", "question": question, "cypher": translation.cypher, "error": str(e)}

    answer = explain(client, question, translation.cypher, rows)

    return {
        "status": "ok",
        "question": question,
        "summary": answer.summary,
        "cypher": translation.cypher,
        "rows": rows,
    }


def print_result(result: dict) -> None:
    print(f"Q: {result['question']}\n")

    if result["status"] == "refused":
        print(f"Can't answer that with the current schema: {result['refusal_reason']}")
        return
    if result["status"] == "unsafe":
        print(f"Refusing to run this query: {result['reason']}")
        return
    if result["status"] == "error":
        print(f"Query failed to run:\n{result['cypher']}\n\nError: {result['error']}")
        return

    print(result["summary"])
    print("\n--- underlying query ---")
    print(result["cypher"])
    print(f"\n--- {len(result['rows'])} row(s) ---")
    for row in result["rows"]:
        print(json.dumps(row, default=str))


def main():
    if len(sys.argv) < 2:
        print('Usage: python nl_query/ask.py "<question>"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])

    # db.connect() loads .env as a side effect (see common/db.py) — it must
    # run before the Anthropic client reads ANTHROPIC_API_KEY from the
    # environment, or the key won't be there yet.
    driver = db.connect()
    client = anthropic.Anthropic()
    try:
        with driver.session() as session:
            print_result(ask(client, session, question))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
