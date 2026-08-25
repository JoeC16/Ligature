"""Cypher writes for the POST endpoints — reuses common/db.py's MERGE-based
write_nodes/write_edges, same as every other step, even though a fresh
uuid4 id colliding is practically impossible."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import db  # noqa: E402


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_treatment(session, injury_id: str, physio_id: str, physio_name: str, type_: str, treatment_date: date, notes: str | None) -> str:
    treatment_id = new_id("treatment")
    row = {"id": treatment_id, "date": treatment_date.isoformat(), "type": type_, "practitioner": physio_name}
    if notes:
        row["notes"] = notes
    db.write_nodes(session, "Treatment", [row])
    db.write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (p:Physio {id: row.physio_id}), (t:Treatment {id: row.treatment_id})
        MERGE (p)-[:ADMINISTERED]->(t)
        """,
        [{"physio_id": physio_id, "treatment_id": treatment_id}],
    )
    db.write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (t:Treatment {id: row.treatment_id}), (i:Injury {id: row.injury_id})
        MERGE (t)-[:TARGETS]->(i)
        """,
        [{"treatment_id": treatment_id, "injury_id": injury_id}],
    )
    return treatment_id


def create_rehab_session(
    session,
    treatment_id: str,
    treatment_date: date,
    rehab_date: date,
    protocol: str,
    load_prescribed: str,
    rpe_reported: float,
    completed: bool,
) -> tuple[str, int]:
    rehab_id = new_id("rehab")
    days_gap = (rehab_date - treatment_date).days
    row = {
        "id": rehab_id,
        "date": rehab_date.isoformat(),
        "protocol": protocol,
        "load_prescribed": load_prescribed,
        "rpe_reported": rpe_reported,
        "completed": completed,
    }
    db.write_nodes(session, "RehabSession", [row])
    db.write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (t:Treatment {id: row.treatment_id}), (r:RehabSession {id: row.rehab_id})
        MERGE (t)-[:FOLLOWED_BY {days_gap: row.days_gap}]->(r)
        """,
        [{"treatment_id": treatment_id, "rehab_id": rehab_id, "days_gap": days_gap}],
    )
    return rehab_id, days_gap


def create_outcome(session, rehab_session_id: str, result: str, outcome_date: date) -> str:
    outcome_id = new_id("outcome")
    row = {"id": outcome_id, "result": result, "date": outcome_date.isoformat()}
    db.write_nodes(session, "Outcome", [row])
    db.write_edges(
        session,
        """
        UNWIND $rows AS row
        MATCH (r:RehabSession {id: row.rehab_id}), (o:Outcome {id: row.outcome_id})
        MERGE (r)-[:PRODUCED]->(o)
        """,
        [{"rehab_id": rehab_session_id, "outcome_id": outcome_id}],
    )
    return outcome_id


def resolve_flag(session, flag_id: str, resolution_state: str, notes: str | None) -> None:
    row = {"id": flag_id, "resolution_state": resolution_state}
    if notes:
        row["resolution_notes"] = notes
    db.write_nodes(session, "Flag", [row])
