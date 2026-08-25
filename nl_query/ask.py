"""Text-to-Cypher NL query layer (build order step 5) — standalone prototype
per CLAUDE.md ("can be prototyped standalone before full integration"), not
wired into api/app.py yet.

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


def ask(client, session, question: str) -> None:
    print(f"Q: {question}\n")

    translation = translate(client, question)
    if translation.cypher is None:
        print(f"Can't answer that with the current schema: {translation.refusal_reason}")
        return

    try:
        check_read_only(translation.cypher)
    except UnsafeQueryError as e:
        print(f"Refusing to run this query: {e}")
        return

    try:
        rows = run_read_only(session, translation.cypher)
    except Exception as e:
        print(f"Query failed to run:\n{translation.cypher}\n\nError: {e}")
        return

    answer = explain(client, question, translation.cypher, rows)

    print(answer.summary)
    print("\n--- underlying query ---")
    print(translation.cypher)
    print(f"\n--- {len(rows)} row(s) ---")
    for row in rows:
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
            ask(client, session, question)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
