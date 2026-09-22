"""Shared graph DB connection + MERGE-based write helpers. Runs against
Memgraph everywhere (local dev via docker-compose.yml, the bundled
free-tier deploy) through the `neo4j` driver package -- Memgraph speaks
the same Bolt protocol and Cypher dialect Neo4j's official Python driver
expects, so that package name is the correct one to depend on regardless
of which graph database is actually running.

Used by both `seed/seed_data.py` (wipe-and-reload dev/demo data) and
`ingest/ingest_data.py` (additive, rerunnable real-data ingestion). Both
write the same way: MERGE on a stable `id`, `SET n += row` for the rest —
so importing the same row twice updates it in place rather than duplicating.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTRAINTS_FILE = REPO_ROOT / "schema" / "constraints.cypher"


def connect():
    load_dotenv(REPO_ROOT / ".env")
    uri = os.environ.get("GRAPH_DB_URI", "bolt://localhost:7687")
    user = os.environ.get("GRAPH_DB_USER", "memgraph")
    password = os.environ.get("GRAPH_DB_PASSWORD", "unused")

    print(f"Connecting to {uri} ...")
    # Memgraph's community build (what this project runs everywhere)
    # doesn't enforce authentication -- user/password are passed only
    # because the driver's API always expects an auth tuple; there is no
    # real credential to set, rotate, or mistype here.
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver


def run_constraints(session):
    text = CONSTRAINTS_FILE.read_text()
    statements = [s.strip() for s in text.split(";")]
    for statement in statements:
        # Strip full-line comments before checking if anything executable remains.
        lines = [line for line in statement.splitlines() if not line.strip().startswith("//")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            session.run(cleaned)


def wipe(session):
    session.run("MATCH (n) DETACH DELETE n")


def write_nodes(session, label: str, rows: list[dict], exclude_keys: set[str] = frozenset()):
    if not rows:
        return
    clean_rows = [{k: v for k, v in row.items() if k not in exclude_keys} for row in rows]
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{id: row.id}})
        SET n += row
        """,
        rows=clean_rows,
    )


def write_edges(session, query: str, rows: list[dict]):
    if not rows:
        return
    session.run(query, rows=rows)


def print_summary(session):
    node_counts = session.run(
        """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(*) AS count
        ORDER BY label
        """
    ).data()
    edge_counts = session.run(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS type, count(*) AS count
        ORDER BY type
        """
    ).data()

    print("\nNodes:")
    for row in node_counts:
        print(f"  {row['label']:<16} {row['count']}")
    print("\nRelationships:")
    for row in edge_counts:
        print(f"  {row['type']:<20} {row['count']}")
