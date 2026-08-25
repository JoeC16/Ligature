"""Flagging agent — pure computation, no Neo4j (same split as
pattern_engine/engine.py, and for the same reason: testable against real
generated data without a live database).

For one athlete, as of a reference date: compute their rolling-window
deviation signature (reusing pattern_engine's own math, not a copy of it),
then compare it against every prior injury's persisted signature — the
athlete's own past injuries and every other athlete's are compared
identically, which is what makes CLAUDE.md's "the athlete's own prior
injury signature" and "cross-squad clusters" fall out of one loop instead
of two.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pattern_engine"))
from engine import compute_signature_at, jaccard  # noqa: E402

DEFAULT_THRESHOLD = 0.5  # matches pattern_engine.engine.SIMILARITY_THRESHOLD


def _d(value: str) -> date:
    return date.fromisoformat(value)


def flag_id(athlete_id: str, matched_injury_id: str, date_str: str) -> str:
    """Deterministic — the same athlete matching the same historical
    injury on the same day always yields the same id, so a same-day rerun
    MERGEs onto the existing Flag (and its resolution_state) rather than
    duplicating it."""
    key = "|".join([athlete_id, matched_injury_id, date_str])
    return "flag-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def compute_flags_for_athlete(
    athlete: dict,
    reference_date: date,
    athlete_metrics: list[dict],
    athlete_wellness: list[dict],
    historical_injuries: list[dict],
) -> list[dict]:
    """historical_injuries: every injury with a persisted signature,
    already filtered by the caller to date < reference_date (so an
    athlete's own not-yet-happened injury, if evaluating a past
    `--as-of` point, is never compared against).

    Returns a Flag row per matching historical injury clearing this
    athlete's threshold — kept separate rather than merged into one
    blended flag, so each stays traceable to one specific matched case.
    """
    threshold = athlete.get("flag_threshold") or DEFAULT_THRESHOLD

    current = compute_signature_at(reference_date, athlete_metrics, athlete_wellness)
    current_fields = set(current["signature"].keys())
    if not current_fields:
        return []

    flags = []
    for injury in historical_injuries:
        hist_fields = set(injury["deviating_fields"])
        if not hist_fields:
            continue
        confidence = jaccard(current_fields, hist_fields)
        shared = current_fields & hist_fields
        if confidence is not None and confidence >= threshold and shared:
            flags.append(
                {
                    "id": flag_id(athlete["id"], injury["id"], reference_date.isoformat()),
                    "athlete_id": athlete["id"],
                    "matched_injury_id": injury["id"],
                    "confidence": confidence,
                    "shared_metrics": sorted(shared),
                    "date": reference_date.isoformat(),
                }
            )
    return flags


def latest_data_date(athlete_metrics: list[dict], athlete_wellness: list[dict]) -> date | None:
    """The athlete's own most recent Session/WellnessEntry date, plus one
    day — the default reference date when no --as-of override is given,
    since a real nightly job runs relative to whatever data has landed,
    not a fixed calendar date. None if the athlete has no data at all."""
    dates = [_d(m["date"]) for m in athlete_metrics] + [_d(w["date"]) for w in athlete_wellness]
    if not dates:
        return None
    return max(dates) + timedelta(days=1)
