"""Seed the local Neo4j instance with the Ligature schema + synthetic data.

Usage:
    python seed/seed_data.py

Rerunnable: wipes the graph before reloading, and generation is seeded
(see generators.SEED) so every run produces identical data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generators  # noqa: E402
import hamstring_pattern  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTRAINTS_FILE = REPO_ROOT / "schema" / "constraints.cypher"


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


def load(session, data: dict, pattern_edges: dict):
    # --- Nodes ---
    write_nodes(session, "Athlete", data["athletes"], exclude_keys={"baseline"})
    write_nodes(session, "Session", data["sessions"])
    write_nodes(session, "SessionMetric", data["session_metrics"], exclude_keys={"session_id", "athlete_id"})
    write_nodes(session, "WellnessEntry", data["wellness_entries"], exclude_keys={"athlete_id"})
    write_nodes(session, "Physio", data["physios"])
    write_nodes(session, "Injury", data["injuries"], exclude_keys={"athlete_id"})
    write_nodes(session, "Treatment", data["treatments"], exclude_keys={"injury_id", "physio_id"})
    write_nodes(session, "RehabSession", data["rehab_sessions"], exclude_keys={"treatment_id"})
    write_nodes(session, "Outcome", data["outcomes"], exclude_keys={"rehab_session_id"})
    write_nodes(session, "ClinicalNote", data["clinical_notes"], exclude_keys={"injury_id"})

    # --- Edges ---
    edges = data["edges"]

    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (s:Session {id: row.session_id})
        MERGE (a)-[:PARTICIPATED_IN]->(s)
        """,
        edges["participated_in"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (s:Session {id: row.session_id}), (m:SessionMetric {id: row.metric_id})
        MERGE (s)-[:PRODUCED]->(m)
        """,
        edges["produced_metric"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (w:WellnessEntry {id: row.wellness_id})
        MERGE (a)-[:REPORTED]->(w)
        """,
        edges["reported"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (i:Injury {id: row.injury_id})
        MERGE (a)-[:SUSTAINED]->(i)
        """,
        edges["sustained"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (p:Physio {id: row.physio_id}), (t:Treatment {id: row.treatment_id})
        MERGE (p)-[:ADMINISTERED]->(t)
        """,
        edges["administered"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (t:Treatment {id: row.treatment_id}), (i:Injury {id: row.injury_id})
        MERGE (t)-[:TARGETS]->(i)
        """,
        edges["targets"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (t:Treatment {id: row.treatment_id}), (r:RehabSession {id: row.rehab_id})
        MERGE (t)-[:FOLLOWED_BY {days_gap: row.days_gap}]->(r)
        """,
        edges["followed_by"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (r:RehabSession {id: row.rehab_id}), (o:Outcome {id: row.outcome_id})
        MERGE (r)-[:PRODUCED]->(o)
        """,
        edges["produced_outcome"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (i:Injury {id: row.injury_id}), (n:ClinicalNote {id: row.note_id})
        MERGE (i)-[:HAS_NOTE]->(n)
        """,
        edges["has_note"],
    )

    # --- Pattern-engine stand-in edges (see hamstring_pattern.py) ---
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (m:SessionMetric {id: row.metric_id}), (i:Injury {id: row.injury_id})
        MERGE (m)-[p:PRECEDED]->(i)
        SET p.lag_days = row.lag_days, p.correlation_strength = row.correlation_strength
        """,
        pattern_edges["preceded"],
    )
    write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (i1:Injury {id: row.injury_id_from}), (i2:Injury {id: row.injury_id_to})
        MERGE (i1)-[s:SIMILAR_PATTERN_TO]->(i2)
        SET s.shared_metrics = row.shared_metrics, s.confidence = row.confidence
        """,
        pattern_edges["similar_pattern_to"],
    )


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


def main():
    load_dotenv(REPO_ROOT / ".env")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "ligature-dev-pw")

    print(f"Connecting to {uri} ...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()

    with driver.session() as session:
        print("Applying schema constraints...")
        run_constraints(session)

        print("Wiping existing graph data...")
        wipe(session)

        print("Generating synthetic season data...")
        data = generators.generate_all()
        pattern_edges = hamstring_pattern.build_pattern_edges(data)

        print("Writing to Neo4j...")
        load(session, data, pattern_edges)

        print_summary(session)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
