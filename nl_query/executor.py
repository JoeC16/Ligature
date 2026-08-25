"""Step 3: run generated Cypher inside a Neo4j read transaction — the
second, DB-level layer of read-only enforcement (the first is guard.py's
keyword check, which runs before this is ever called). Neo4j itself
rejects a write inside a read transaction, so this isn't just trusting
the guard."""

from __future__ import annotations


def run_read_only(session, cypher: str) -> list[dict]:
    return session.execute_read(lambda tx: tx.run(cypher).data())
