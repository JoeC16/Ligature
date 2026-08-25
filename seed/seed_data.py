"""Seed the local Neo4j instance with the Ligature schema + synthetic data.

Usage:
    python seed/seed_data.py

Rerunnable: wipes the graph before reloading, and generation is seeded
(see generators.SEED) so every run produces identical data.

Loads raw data only — PRECEDED and SIMILAR_PATTERN_TO are exclusively
computed by pattern_engine/run_pattern_engine.py, run that next.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT))
import generators  # noqa: E402
from common import db  # noqa: E402

write_nodes = db.write_nodes
write_edges = db.write_edges


def load(session, data: dict):
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


def main():
    driver = db.connect()

    with driver.session() as session:
        print("Applying schema constraints...")
        db.run_constraints(session)

        print("Wiping existing graph data...")
        db.wipe(session)

        print("Generating synthetic season data...")
        data = generators.generate_all()

        print("Writing to Neo4j...")
        load(session, data)

        db.print_summary(session)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
