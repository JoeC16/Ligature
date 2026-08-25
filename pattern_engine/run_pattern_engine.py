"""Run the pattern engine against whatever's currently in the graph.

Usage:
    python pattern_engine/run_pattern_engine.py

A background job, not a per-query computation (per CLAUDE.md): pulls every
injury and its athlete's full SessionMetric/WellnessEntry history, scores
deviation from that athlete's own baseline, and writes PRECEDED /
SIMILAR_PATTERN_TO edges back. These two edge types are exclusively
pattern-engine-owned, so each run deletes and recomputes them from the
graph's current state rather than accumulating stale edges across runs.

Also persists each injury's `deviating_fields` (the signature's field
names) onto the Injury node itself — the pattern engine already computes
this signature in memory to build SIMILAR_PATTERN_TO, but never used to
write it anywhere queryable. flagging_agent/ (build order step 6) needs
exactly this: "the athlete's own prior injury signature" and "cross-squad
clusters" to compare a new rolling window against are both just prior
injuries' persisted signatures. Purely additive — one more property,
doesn't change PRECEDED/SIMILAR_PATTERN_TO at all.

Safe to run any time after seed_data.py and/or ingest_data.py have loaded
data — this only reads Session/SessionMetric/WellnessEntry/Injury/Athlete
and writes PRECEDED/SIMILAR_PATTERN_TO plus that one Injury property.
"""

from __future__ import annotations

import sys
from pathlib import Path

PATTERN_ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PATTERN_ENGINE_DIR.parent
sys.path.insert(0, str(PATTERN_ENGINE_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402
from engine import compute_all  # noqa: E402
from queries import delete_pattern_edges, pull_all  # noqa: E402

PRECEDED_QUERY = """
    UNWIND $rows AS row
    MATCH (m:SessionMetric {id: row.metric_id}), (i:Injury {id: row.injury_id})
    MERGE (m)-[p:PRECEDED]->(i)
    SET p.lag_days = row.lag_days, p.correlation_strength = row.correlation_strength
"""

SIMILAR_PATTERN_TO_QUERY = """
    UNWIND $rows AS row
    MATCH (i1:Injury {id: row.injury_id_from}), (i2:Injury {id: row.injury_id_to})
    MERGE (i1)-[s:SIMILAR_PATTERN_TO]->(i2)
    SET s.shared_metrics = row.shared_metrics, s.confidence = row.confidence
"""


def main():
    driver = db.connect()

    with driver.session() as session:
        print("Pulling injuries + athlete history from Neo4j...")
        pulled = pull_all(session)
        print(f"  {len(pulled['injuries'])} injuries across {len(pulled['metrics_by_athlete'])} athletes")

        print("Scoring deviation from each athlete's own baseline...")
        result = compute_all(pulled)

        print("Clearing previously-computed PRECEDED / SIMILAR_PATTERN_TO edges...")
        delete_pattern_edges(session)

        print("Writing new edges...")
        db.write_edges(session, PRECEDED_QUERY, result["preceded"])
        db.write_edges(session, SIMILAR_PATTERN_TO_QUERY, result["similar_pattern_to"])

        print("Persisting each injury's deviation signature (deviating_fields)...")
        db.write_nodes(
            session,
            "Injury",
            [{"id": injury_id, "deviating_fields": sorted(sig.keys())} for injury_id, sig in result["signatures"].items()],
        )

        print(f"\nPRECEDED edges written: {len(result['preceded'])}")
        for edge in result["preceded"]:
            print(f"    {edge['metric_id']} -> {edge['injury_id']}  lag={edge['lag_days']}d  corr={edge['correlation_strength']}")

        print(f"\nSIMILAR_PATTERN_TO edges written: {len(result['similar_pattern_to'])}")
        for edge in result["similar_pattern_to"]:
            shared = ", ".join(edge["shared_metrics"])
            print(f"    {edge['injury_id_from']} -> {edge['injury_id_to']}  confidence={edge['confidence']}  shared=[{shared}]")

        no_pattern = [i["id"] for i in pulled["injuries"] if not result["signatures"].get(i["id"])]
        if no_pattern:
            print(f"\nNo deviation signature found for {len(no_pattern)} injuries (no lead-in above threshold): {', '.join(no_pattern)}")

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
