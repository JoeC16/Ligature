"""Flagging agent (build order step 6) — for every athlete, compares their
current rolling window against every prior injury's persisted deviation
signature, and writes a Flag when one clears that athlete's confidence
threshold.

Usage:
    python flagging_agent/run_flagging_agent.py
    python flagging_agent/run_flagging_agent.py --as-of 2025-02-16

Default reference date is per-athlete: their own most recent Session/
WellnessEntry date + 1 day — a real nightly job runs relative to whatever
data has landed, not a fixed calendar date. --as-of overrides that
globally, for testing/demos (see README for why the seed data only
produces a real flag with an --as-of override, not by default).

Requires pattern_engine/run_pattern_engine.py to have run at least once —
otherwise no injury has a persisted deviation signature yet to compare
against, and this correctly finds nothing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

FLAGGING_AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = FLAGGING_AGENT_DIR.parent
sys.path.insert(0, str(FLAGGING_AGENT_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402

from agent import compute_flags_for_athlete, latest_data_date  # noqa: E402
from fetch import fetch_athlete_metrics, fetch_athlete_wellness, fetch_athletes, fetch_injury_signatures  # noqa: E402

FLAG_QUERY = """
    UNWIND $rows AS row
    MERGE (f:Flag {id: row.id})
    ON CREATE SET f.resolution_state = 'unreviewed'
    SET f.date = row.date, f.confidence = row.confidence
"""

CURRENTLY_QUERY = """
    UNWIND $rows AS row
    MATCH (a:Athlete {id: row.athlete_id}), (f:Flag {id: row.id})
    MERGE (a)-[:CURRENTLY]->(f)
"""

MATCHES_QUERY = """
    UNWIND $rows AS row
    MATCH (f:Flag {id: row.id}), (i:Injury {id: row.matched_injury_id})
    MERGE (f)-[m:MATCHES]->(i)
    SET m.shared_metrics = row.shared_metrics
"""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", help="Evaluate every athlete as of this date (YYYY-MM-DD) instead of their own latest data date")
    return parser.parse_args()


def main():
    args = parse_args()
    override_date = date.fromisoformat(args.as_of) if args.as_of else None

    driver = db.connect()
    with driver.session() as session:
        athletes = fetch_athletes(session)
        injury_signatures = fetch_injury_signatures(session)
        print(f"{len(athletes)} athletes, {len(injury_signatures)} scored injuries to compare against\n")

        all_flags = []
        for athlete in athletes:
            metrics = fetch_athlete_metrics(session, athlete["id"])
            wellness = fetch_athlete_wellness(session, athlete["id"])

            reference_date = override_date or latest_data_date(metrics, wellness)
            if reference_date is None:
                print(f"  {athlete['name']}: no data, skipping")
                continue

            historical = [inj for inj in injury_signatures if date.fromisoformat(inj["date"]) < reference_date]
            flags = compute_flags_for_athlete(athlete, reference_date, metrics, wellness, historical)
            all_flags.extend(flags)

            label = f"{len(flags)} flag(s)" if flags else "no flags"
            print(f"  {athlete['name']} (as of {reference_date.isoformat()}): {label}")
            for flag in flags:
                print(f"    -> matches {flag['matched_injury_id']}  confidence={flag['confidence']}  shared={flag['shared_metrics']}")

        print(f"\nWriting {len(all_flags)} flag(s)...")
        db.write_edges(session, FLAG_QUERY, all_flags)
        db.write_edges(session, CURRENTLY_QUERY, all_flags)
        db.write_edges(session, MATCHES_QUERY, all_flags)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
