"""Cypher for the GET endpoints — the "what's still open" reads that back
the treatment/rehab/outcome POST endpoints' dropdowns, plus the flags a
physio still needs to review (build order step 6's resolution write-back).
"""

from __future__ import annotations


def fetch_open_injuries(session) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury)
        WHERE NOT (i)<-[:TARGETS]-(:Treatment)
        RETURN i.id AS id, a.id AS athlete_id, a.name AS athlete_name,
               i.type AS type, i.body_part AS body_part, i.date AS date
        ORDER BY i.date
        """
    ).data()


def fetch_physios(session) -> list[dict]:
    return session.run("MATCH (p:Physio) RETURN p.id AS id, p.name AS name ORDER BY p.name").data()


def fetch_open_treatments(session) -> list[dict]:
    return session.run(
        """
        MATCH (t:Treatment)-[:TARGETS]->(i:Injury)
        WHERE NOT (t)-[:FOLLOWED_BY]->(:RehabSession)
        RETURN t.id AS id, i.id AS injury_id, t.date AS date, t.type AS type, t.practitioner AS practitioner
        ORDER BY t.date
        """
    ).data()


def fetch_open_rehab_sessions(session) -> list[dict]:
    return session.run(
        """
        MATCH (t:Treatment)-[:FOLLOWED_BY]->(r:RehabSession)
        WHERE NOT (r)-[:PRODUCED]->(:Outcome)
        RETURN r.id AS id, t.id AS treatment_id, r.date AS date, r.protocol AS protocol
        ORDER BY r.date
        """
    ).data()


def injury_exists(session, injury_id: str) -> bool:
    result = session.run("MATCH (i:Injury {id: $id}) RETURN i.id AS id", id=injury_id).single()
    return result is not None


def fetch_physio(session, physio_id: str) -> dict | None:
    result = session.run("MATCH (p:Physio {id: $id}) RETURN p.id AS id, p.name AS name", id=physio_id).single()
    return dict(result) if result else None


def fetch_treatment_date(session, treatment_id: str) -> str | None:
    result = session.run("MATCH (t:Treatment {id: $id}) RETURN t.date AS date", id=treatment_id).single()
    return result["date"] if result else None


def rehab_session_exists(session, rehab_session_id: str) -> bool:
    result = session.run(
        "MATCH (r:RehabSession {id: $id}) RETURN r.id AS id", id=rehab_session_id
    ).single()
    return result is not None


def fetch_unreviewed_flags(session) -> list[dict]:
    return session.run(
        """
        MATCH (a:Athlete)-[:CURRENTLY]->(f:Flag {resolution_state: 'unreviewed'})-[rel:MATCHES]->(i:Injury)<-[:SUSTAINED]-(ma:Athlete)
        RETURN f.id AS id, a.id AS athlete_id, a.name AS athlete_name, f.date AS date, f.confidence AS confidence,
               rel.shared_metrics AS shared_metrics, i.id AS matched_injury_id, i.type AS matched_injury_type,
               ma.name AS matched_injury_athlete_name
        ORDER BY f.date DESC
        """
    ).data()


def flag_exists(session, flag_id: str) -> bool:
    result = session.run("MATCH (f:Flag {id: $id}) RETURN f.id AS id", id=flag_id).single()
    return result is not None
