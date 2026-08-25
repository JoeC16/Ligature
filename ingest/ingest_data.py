"""Ingest real (or real-shaped) club CSV exports into the Ligature graph.

Unlike seed/seed_data.py, this never wipes anything — it's additive/upsert,
meant to be run repeatedly (once per scheduled export) against a live graph.
Each source is independent and optional; a real deployment runs each on its
own schedule as that system's export lands.

Usage:
    python ingest/ingest_data.py \\
        --roster ingest/sample_data/athlete_roster.csv \\
        --gps ingest/sample_data/gps_export.csv \\
        --wellness ingest/sample_data/wellness_export.csv \\
        --injuries ingest/sample_data/injury_log.csv

Any of --gps / --wellness / --injuries may be omitted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

INGEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = INGEST_DIR.parent
sys.path.insert(0, str(INGEST_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402
from roster import load_roster  # noqa: E402
from sources.gps import import_gps  # noqa: E402
from sources.injuries import import_injuries  # noqa: E402
from sources.wellness import import_wellness  # noqa: E402

EDGE_QUERIES = {
    "participated_in": """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (s:Session {id: row.session_id})
        MERGE (a)-[:PARTICIPATED_IN]->(s)
    """,
    "produced_metric": """
        UNWIND $rows AS row
        MATCH (s:Session {id: row.session_id}), (m:SessionMetric {id: row.metric_id})
        MERGE (s)-[:PRODUCED]->(m)
    """,
    "reported": """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (w:WellnessEntry {id: row.wellness_id})
        MERGE (a)-[:REPORTED]->(w)
    """,
    "sustained": """
        UNWIND $rows AS row
        MATCH (a:Athlete {id: row.athlete_id}), (i:Injury {id: row.injury_id})
        MERGE (a)-[:SUSTAINED]->(i)
    """,
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roster", help="Athlete roster CSV (required if any source file is given)")
    parser.add_argument("--gps", help="GPS/session export CSV")
    parser.add_argument("--wellness", help="Wellness survey export CSV")
    parser.add_argument("--injuries", help="Injury log CSV")
    args = parser.parse_args()

    if any([args.gps, args.wellness, args.injuries]) and not args.roster:
        parser.error("--roster is required when any of --gps/--wellness/--injuries is given")
    if not any([args.roster, args.gps, args.wellness, args.injuries]):
        parser.error("nothing to do — pass at least --roster with one of --gps/--wellness/--injuries")
    return args


def report(source_name: str, result: dict):
    stats = result["stats"]
    print(f"\n{source_name}: read {stats['read']}, loaded {stats['loaded']}, skipped {stats['skipped']}")
    for warning in result.get("warnings", []):
        print(f"    warning (line {warning['line']}): {warning['reason']}")
    for skip in result["skipped_rows"]:
        print(f"    skipped (line {skip['line']}): {skip['reason']}")


def main():
    args = parse_args()
    driver = db.connect()

    with driver.session() as session:
        print("Applying schema constraints...")
        db.run_constraints(session)

        print(f"Loading roster from {args.roster} ...")
        roster = load_roster(args.roster)
        db.write_nodes(session, "Athlete", roster.athletes)
        print(f"  {len(roster.athletes)} athletes upserted")

        if args.gps:
            result = import_gps(args.gps, roster)
            db.write_nodes(session, "Session", result["sessions"])
            db.write_nodes(session, "SessionMetric", result["session_metrics"])
            db.write_edges(session, EDGE_QUERIES["participated_in"], result["edges"]["participated_in"])
            db.write_edges(session, EDGE_QUERIES["produced_metric"], result["edges"]["produced_metric"])
            report("GPS/session", result)

        if args.wellness:
            result = import_wellness(args.wellness, roster)
            db.write_nodes(session, "WellnessEntry", result["wellness_entries"])
            db.write_edges(session, EDGE_QUERIES["reported"], result["edges"]["reported"])
            report("Wellness", result)

        if args.injuries:
            result = import_injuries(args.injuries, roster)
            db.write_nodes(session, "Injury", result["injuries"])
            db.write_edges(session, EDGE_QUERIES["sustained"], result["edges"]["sustained"])
            report("Injuries", result)

        db.print_summary(session)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
