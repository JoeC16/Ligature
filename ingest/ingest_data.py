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


def _trim(result: dict, *raw_keys: str) -> dict:
    """Drops the raw entity/edge lists a source importer returns (already
    written to the graph by this point) from its report, keeping just
    stats/skipped_rows/warnings/file_error -- the shape both the CLI's
    report() and api/app.py's POST /ingest JSON response actually need.
    Returning the full ingested dataset back to a browser on every upload
    would make the response arbitrarily large for no reason."""
    return {k: v for k, v in result.items() if k not in raw_keys}


def run_ingest(
    session,
    roster_path: str,
    gps_path: str | None = None,
    wellness_path: str | None = None,
    injuries_path: str | None = None,
) -> dict:
    """Runs the full ingest pipeline against an already-open session and
    returns a structured, JSON-serializable report -- no printing, no CLI
    argument parsing -- so both this module's own CLI (main(), below) and
    api/app.py's POST /ingest route drive the identical pipeline and get
    identical results back. Same split as nl_query/ask.py's
    ask()/print_result(): one function returns data, the CLI-only caller
    turns it into terminal output.

    result["aborted"] is True only when the roster itself fails to load
    (a missing/misnamed name column, most likely) -- every other source
    resolves athletes against it, so there's nothing meaningful to ingest
    without it. A gps/wellness/injuries-specific file_error, by contrast,
    doesn't abort the run; the other sources are independent and still go
    ahead."""
    db.run_constraints(session)

    roster = load_roster(roster_path)
    result = {
        "roster": {"stats": roster.stats, "skipped_rows": roster.skipped_rows, "file_error": roster.file_error},
        "gps": None,
        "wellness": None,
        "injuries": None,
        "aborted": bool(roster.file_error),
    }
    if roster.file_error:
        return result
    db.write_nodes(session, "Athlete", roster.athletes)

    if gps_path:
        gps_result = import_gps(gps_path, roster)
        if not gps_result.get("file_error"):
            db.write_nodes(session, "Session", gps_result["sessions"])
            db.write_nodes(session, "SessionMetric", gps_result["session_metrics"])
            db.write_edges(session, EDGE_QUERIES["participated_in"], gps_result["edges"]["participated_in"])
            db.write_edges(session, EDGE_QUERIES["produced_metric"], gps_result["edges"]["produced_metric"])
        result["gps"] = _trim(gps_result, "sessions", "session_metrics", "edges")

    if wellness_path:
        wellness_result = import_wellness(wellness_path, roster)
        if not wellness_result.get("file_error"):
            db.write_nodes(session, "WellnessEntry", wellness_result["wellness_entries"])
            db.write_edges(session, EDGE_QUERIES["reported"], wellness_result["edges"]["reported"])
        result["wellness"] = _trim(wellness_result, "wellness_entries", "edges")

    if injuries_path:
        injuries_result = import_injuries(injuries_path, roster)
        if not injuries_result.get("file_error"):
            db.write_nodes(session, "Injury", injuries_result["injuries"])
            db.write_edges(session, EDGE_QUERIES["sustained"], injuries_result["edges"]["sustained"])
        result["injuries"] = _trim(injuries_result, "injuries", "edges")

    return result


def report(source_name: str, result: dict):
    file_error = result.get("file_error")
    if file_error:
        # A missing/misnamed required column -- surfaced once, here,
        # instead of every row failing with the same confusing reason.
        print(f"\n{source_name}: {file_error}")
        return
    stats = result["stats"]
    print(f"\n{source_name}: read {stats['read']}, loaded {stats['loaded']}, skipped {stats['skipped']}")
    for warning in result.get("warnings", []):
        print(f"    warning (line {warning['line']}): {warning['reason']}")
    for skip in result["skipped_rows"]:
        print(f"    skipped (line {skip['line']}): {skip['reason']}")


def print_result(result: dict):
    report("Roster", result["roster"])
    if result["aborted"]:
        print("\nAborting -- every other source resolves athletes against the roster.")
        return
    for source_name, key in [("GPS/session", "gps"), ("Wellness", "wellness"), ("Injuries", "injuries")]:
        if result[key] is not None:
            report(source_name, result[key])


def main():
    args = parse_args()
    driver = db.connect()

    with driver.session() as session:
        result = run_ingest(session, args.roster, args.gps, args.wellness, args.injuries)
        print_result(result)
        if not result["aborted"]:
            db.print_summary(session)

    driver.close()
    if result["aborted"]:
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
