"""Cypher pull layer for the pattern engine — thin, no logic.

Reshapes what's in the graph into the plain-dict shape engine.py's pure
functions consume: {"injuries": [...], "metrics_by_athlete": {...},
"wellness_by_athlete": {...}}.
"""

from __future__ import annotations

from collections import defaultdict


def fetch_injuries(session) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury)
        RETURN i.id AS id, a.id AS athlete_id, i.date AS date, i.type AS type, i.body_part AS body_part
        ORDER BY i.date
        """
    ).data()


def fetch_all_metrics(session) -> dict[str, list[dict]]:
    """Every athlete's SessionMetrics in one round trip, grouped by athlete
    id in Python -- not one MATCH per athlete. On a squad-sized graph (30
    athletes) that was 30 separate queries each paying their own Bolt
    round-trip + query-plan overhead, which is exactly the kind of fixed
    per-call cost that adds up fastest on a CPU-throttled free-tier host."""
    rows = session.run(
        """
        MATCH (a:Athlete)-[:PARTICIPATED_IN]->(s:Session)-[:PRODUCED]->(m:SessionMetric)
        RETURN a.id AS athlete_id, m.id AS id, s.date AS date, s.type AS type,
               m.hsr_distance_m AS hsr_distance_m, m.sprint_count AS sprint_count,
               m.accel_decel_load AS accel_decel_load, m.total_distance_m AS total_distance_m
        ORDER BY a.id, s.date
        """
    ).data()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.pop("athlete_id")].append(row)
    return grouped


def fetch_all_wellness(session) -> dict[str, list[dict]]:
    """Same batching rationale as fetch_all_metrics."""
    rows = session.run(
        """
        MATCH (a:Athlete)-[:REPORTED]->(w:WellnessEntry)
        RETURN a.id AS athlete_id, w.id AS id, w.date AS date, w.sleep_hours AS sleep_hours,
               w.sleep_quality AS sleep_quality, w.hrv AS hrv, w.soreness AS soreness, w.mood AS mood
        ORDER BY a.id, w.date
        """
    ).data()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.pop("athlete_id")].append(row)
    return grouped


def pull_all(session) -> dict:
    injuries = fetch_injuries(session)
    athlete_ids = sorted({i["athlete_id"] for i in injuries})
    all_metrics = fetch_all_metrics(session)
    all_wellness = fetch_all_wellness(session)
    return {
        "injuries": injuries,
        "metrics_by_athlete": {aid: all_metrics.get(aid, []) for aid in athlete_ids},
        "wellness_by_athlete": {aid: all_wellness.get(aid, []) for aid in athlete_ids},
    }


def delete_pattern_edges(session) -> None:
    """Scoped delete — only the two edge types the pattern engine owns.
    Every other node/edge in the graph is untouched."""
    session.run("MATCH ()-[r:PRECEDED]->() DELETE r")
    session.run("MATCH ()-[r:SIMILAR_PATTERN_TO]->() DELETE r")
