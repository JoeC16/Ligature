"""Cypher pull layer for the pattern engine — thin, no logic.

Reshapes what's in Neo4j into the plain-dict shape engine.py's pure
functions consume: {"injuries": [...], "metrics_by_athlete": {...},
"wellness_by_athlete": {...}}.
"""

from __future__ import annotations


def fetch_injuries(session) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury)
        RETURN i.id AS id, a.id AS athlete_id, i.date AS date, i.type AS type, i.body_part AS body_part
        ORDER BY i.date
        """
    ).data()


def fetch_athlete_metrics(session, athlete_id: str) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete {id: $athlete_id})-[:PARTICIPATED_IN]->(s:Session)-[:PRODUCED]->(m:SessionMetric)
        RETURN m.id AS id, s.date AS date, s.type AS type,
               m.hsr_distance_m AS hsr_distance_m, m.sprint_count AS sprint_count,
               m.accel_decel_load AS accel_decel_load, m.total_distance_m AS total_distance_m
        ORDER BY s.date
        """,
        athlete_id=athlete_id,
    ).data()


def fetch_athlete_wellness(session, athlete_id: str) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete {id: $athlete_id})-[:REPORTED]->(w:WellnessEntry)
        RETURN w.id AS id, w.date AS date, w.sleep_hours AS sleep_hours,
               w.sleep_quality AS sleep_quality, w.hrv AS hrv, w.soreness AS soreness, w.mood AS mood
        ORDER BY w.date
        """,
        athlete_id=athlete_id,
    ).data()


def pull_all(session) -> dict:
    injuries = fetch_injuries(session)
    athlete_ids = sorted({i["athlete_id"] for i in injuries})
    return {
        "injuries": injuries,
        "metrics_by_athlete": {aid: fetch_athlete_metrics(session, aid) for aid in athlete_ids},
        "wellness_by_athlete": {aid: fetch_athlete_wellness(session, aid) for aid in athlete_ids},
    }


def delete_pattern_edges(session) -> None:
    """Scoped delete — only the two edge types the pattern engine owns.
    Every other node/edge in the graph is untouched."""
    session.run("MATCH ()-[r:PRECEDED]->() DELETE r")
    session.run("MATCH ()-[r:SIMILAR_PATTERN_TO]->() DELETE r")
