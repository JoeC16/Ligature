"""Read-only enforcement for generated Cypher — the first of two layers
(the second is running the query inside a Neo4j read transaction, see
executor.py, which the server itself rejects a write inside). This layer
exists so an unsafe query never even reaches the database.
"""

from __future__ import annotations

import re

WRITE_KEYWORDS = ["CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "CALL", "LOAD CSV"]

_PATTERNS = [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in WRITE_KEYWORDS]


class UnsafeQueryError(Exception):
    """Raised when generated Cypher contains a write keyword."""


def check_read_only(cypher: str) -> None:
    """Raises UnsafeQueryError if `cypher` contains a write keyword as a
    whole word (so e.g. a property named `created_at` is not a false
    positive — "CREATE" as a substring of a longer identifier doesn't
    match \\b...\\b)."""
    for pattern in _PATTERNS:
        if pattern.search(cypher):
            raise UnsafeQueryError(f"Generated query contains a write keyword ('{pattern.pattern}'), refusing to run it:\n{cypher}")
