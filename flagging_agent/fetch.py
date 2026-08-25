"""Cypher pull layer for the flagging agent — thin, no logic. Reuses
pattern_engine/queries.py's fetch_athlete_metrics/fetch_athlete_wellness
rather than duplicating them; this module only adds what pattern_engine
doesn't already fetch.

Named `fetch.py`, not `queries.py` — pattern_engine/ already has a
queries.py, and this codebase's flat sys.path-based imports resolve a
bare module name to whichever same-named file was put on sys.path most
recently, not by which package it's "supposed" to belong to. Two sibling
packages each shipping their own queries.py is a silent collision, not
namespaced the way a real package import would be.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pattern_engine"))
from queries import fetch_athlete_metrics, fetch_athlete_wellness  # noqa: E402,F401


def fetch_athletes(session) -> list[dict]:
    """id, name, flag_threshold (None if this athlete hasn't been given a
    per-player override — the CLAUDE.md-required configurable threshold)."""
    return session.run(
        "MATCH (a:Athlete) RETURN a.id AS id, a.name AS name, a.flag_threshold AS flag_threshold ORDER BY a.id"
    ).data()


def fetch_injury_signatures(session) -> list[dict]:
    """Every injury pattern_engine has scored (i.e. deviating_fields is
    set — a prior run may not have happened yet, in which case this is
    empty and the flagging agent correctly has nothing to compare
    against)."""
    return session.run(
        """
        MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury)
        WHERE i.deviating_fields IS NOT NULL
        RETURN i.id AS id, a.id AS athlete_id, i.date AS date, i.deviating_fields AS deviating_fields
        ORDER BY i.date
        """
    ).data()
