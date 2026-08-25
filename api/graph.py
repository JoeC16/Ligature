"""Cypher for the frontend graph explorer (build order step 7): a small
curated starting view (fetch_overview) plus label-dispatched expansion
(expand_node), so the frontend never has to reason about which
relationships are "the bulk ones" (an Athlete's ~120 Sessions, ~280
WellnessEntries) versus the handful worth surfacing on a click.

Every node returned carries its full property map (for the detail panel);
every edge carries a computed id ("{type}:{from}->{to}", not Neo4j's
internal relationship id, which isn't a stable public contract) so the
frontend can dedupe edges pulled in from more than one query.
"""

from __future__ import annotations

# Node labels the overview graph shows outright, and the only labels
# expand_node() will dispatch on by name. Anything else it might return
# (SessionMetric, Treatment, Physio, RehabSession, Outcome) falls through
# to a generic, capped one-hop neighbor expansion.
OVERVIEW_LABELS = ("Athlete", "Injury", "Flag")
GENERIC_EXPAND_LIMIT = 25


def _node_return(var: str) -> str:
    return f"{var}.id AS id, labels({var})[0] AS label, properties({var}) AS properties"


def _node_row(record) -> dict:
    return {"id": record["id"], "label": record["label"], "properties": dict(record["properties"])}


def _edge_row(rel_type: str, from_id: str, to_id: str, properties: dict | None = None) -> dict:
    return {
        "id": f"{rel_type}:{from_id}->{to_id}",
        "type": rel_type,
        "from": from_id,
        "to": to_id,
        "properties": dict(properties) if properties else {},
    }


class _Accumulator:
    """Dedupes nodes/edges by id across several session.run() calls."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}

    def add_node(self, record) -> None:
        if record["id"] is None:
            return
        row = _node_row(record)
        self.nodes[row["id"]] = row

    def add_edge(self, rel_type: str, from_id: str, to_id: str, properties: dict | None = None) -> None:
        if from_id is None or to_id is None:
            return
        row = _edge_row(rel_type, from_id, to_id, properties)
        self.edges[row["id"]] = row

    def result(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}


def fetch_overview(session) -> dict:
    """Every Athlete, Injury, and Flag, plus the edges between them
    (SUSTAINED, SIMILAR_PATTERN_TO, CURRENTLY, MATCHES). The starting
    view — small, structural, none of the bulk session/wellness nodes."""
    acc = _Accumulator()

    for label in OVERVIEW_LABELS:
        for record in session.run(f"MATCH (n:{label}) RETURN {_node_return('n')}"):
            acc.add_node(record)

    for record in session.run(
        "MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury) RETURN a.id AS from_id, i.id AS to_id"
    ):
        acc.add_edge("SUSTAINED", record["from_id"], record["to_id"])

    for record in session.run(
        """
        MATCH (i1:Injury)-[r:SIMILAR_PATTERN_TO]->(i2:Injury)
        RETURN i1.id AS from_id, i2.id AS to_id, properties(r) AS properties
        """
    ):
        acc.add_edge("SIMILAR_PATTERN_TO", record["from_id"], record["to_id"], record["properties"])

    for record in session.run(
        "MATCH (a:Athlete)-[:CURRENTLY]->(f:Flag) RETURN a.id AS from_id, f.id AS to_id"
    ):
        acc.add_edge("CURRENTLY", record["from_id"], record["to_id"])

    for record in session.run(
        """
        MATCH (f:Flag)-[r:MATCHES]->(i:Injury)
        RETURN f.id AS from_id, i.id AS to_id, properties(r) AS properties
        """
    ):
        acc.add_edge("MATCHES", record["from_id"], record["to_id"], record["properties"])

    return acc.result()


def fetch_node_label(session, node_id: str) -> str | None:
    result = session.run("MATCH (n {id: $id}) RETURN labels(n)[0] AS label", id=node_id).single()
    return result["label"] if result else None


def _expand_athlete(session, athlete_id: str) -> dict:
    acc = _Accumulator()

    for record in session.run(
        f"""
        MATCH (a:Athlete {{id: $id}})-[:SUSTAINED]->(i:Injury)
        RETURN {_node_return('i')}
        """,
        id=athlete_id,
    ):
        acc.add_node(record)
        acc.add_edge("SUSTAINED", athlete_id, record["id"])

    for record in session.run(
        f"""
        MATCH (a:Athlete {{id: $id}})-[:CURRENTLY]->(f:Flag)
        RETURN {_node_return('f')}
        """,
        id=athlete_id,
    ):
        acc.add_node(record)
        acc.add_edge("CURRENTLY", athlete_id, record["id"])

    # Only the SessionMetrics that actually preceded one of this athlete's
    # injuries — never the full training log (that's ~120 Sessions/season).
    for record in session.run(
        f"""
        MATCH (a:Athlete {{id: $id}})-[:PARTICIPATED_IN]->(:Session)-[:PRODUCED]->(m:SessionMetric)
        MATCH (m)-[r:PRECEDED]->(i:Injury)
        RETURN {_node_return('m')}, i.id AS injury_id, properties(r) AS rel_properties
        """,
        id=athlete_id,
    ):
        acc.add_node(record)
        acc.add_edge("PRECEDED", record["id"], record["injury_id"], record["rel_properties"])

    return acc.result()


def _expand_injury(session, injury_id: str) -> dict:
    acc = _Accumulator()

    # The athlete this injury belongs to — otherwise an injury reached via
    # search (not via its athlete) would render as a disconnected node.
    for record in session.run(
        f"""
        MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury {{id: $id}})
        RETURN {_node_return('a')}
        """,
        id=injury_id,
    ):
        acc.add_node(record)
        acc.add_edge("SUSTAINED", record["id"], injury_id)

    for record in session.run(
        f"""
        MATCH (m:SessionMetric)-[r:PRECEDED]->(i:Injury {{id: $id}})
        RETURN {_node_return('m')}, properties(r) AS rel_properties
        """,
        id=injury_id,
    ):
        acc.add_node(record)
        acc.add_edge("PRECEDED", record["id"], injury_id, record["rel_properties"])

    for record in session.run(
        f"""
        MATCH (i:Injury {{id: $id}})-[r:SIMILAR_PATTERN_TO]->(other:Injury)
        RETURN {_node_return('other')}, properties(r) AS rel_properties
        """,
        id=injury_id,
    ):
        acc.add_node(record)
        acc.add_edge("SIMILAR_PATTERN_TO", injury_id, record["id"], record["rel_properties"])

    for record in session.run(
        f"""
        MATCH (other:Injury)-[r:SIMILAR_PATTERN_TO]->(i:Injury {{id: $id}})
        RETURN {_node_return('other')}, properties(r) AS rel_properties
        """,
        id=injury_id,
    ):
        acc.add_node(record)
        acc.add_edge("SIMILAR_PATTERN_TO", record["id"], injury_id, record["rel_properties"])

    for record in session.run(
        f"""
        MATCH (t:Treatment)-[:TARGETS]->(i:Injury {{id: $id}})
        OPTIONAL MATCH (p:Physio)-[:ADMINISTERED]->(t)
        OPTIONAL MATCH (t)-[:FOLLOWED_BY]->(r:RehabSession)
        OPTIONAL MATCH (r)-[:PRODUCED]->(o:Outcome)
        RETURN {_node_return('t')},
               p.id AS physio_id, p.name AS physio_name,
               r.id AS rehab_id, labels(r)[0] AS rehab_label, properties(r) AS rehab_properties,
               o.id AS outcome_id, labels(o)[0] AS outcome_label, properties(o) AS outcome_properties
        """,
        id=injury_id,
    ):
        acc.add_node(record)  # the Treatment node itself
        acc.add_edge("TARGETS", record["id"], injury_id)

        if record["physio_id"] is not None:
            acc.nodes[record["physio_id"]] = {
                "id": record["physio_id"],
                "label": "Physio",
                "properties": {"id": record["physio_id"], "name": record["physio_name"]},
            }
            acc.add_edge("ADMINISTERED", record["physio_id"], record["id"])

        if record["rehab_id"] is not None:
            acc.nodes[record["rehab_id"]] = {
                "id": record["rehab_id"],
                "label": record["rehab_label"],
                "properties": dict(record["rehab_properties"]),
            }
            acc.add_edge("FOLLOWED_BY", record["id"], record["rehab_id"])

        if record["outcome_id"] is not None:
            acc.nodes[record["outcome_id"]] = {
                "id": record["outcome_id"],
                "label": record["outcome_label"],
                "properties": dict(record["outcome_properties"]),
            }
            acc.add_edge("PRODUCED", record["rehab_id"], record["outcome_id"])

    return acc.result()


def _expand_flag(session, flag_id: str) -> dict:
    acc = _Accumulator()

    for record in session.run(
        f"""
        MATCH (a:Athlete)-[:CURRENTLY]->(f:Flag {{id: $id}})
        RETURN {_node_return('a')}
        """,
        id=flag_id,
    ):
        acc.add_node(record)
        acc.add_edge("CURRENTLY", record["id"], flag_id)

    for record in session.run(
        f"""
        MATCH (f:Flag {{id: $id}})-[r:MATCHES]->(i:Injury)
        RETURN {_node_return('i')}, properties(r) AS rel_properties
        """,
        id=flag_id,
    ):
        acc.add_node(record)
        acc.add_edge("MATCHES", flag_id, record["id"], record["rel_properties"])

    return acc.result()


def _expand_generic(session, node_id: str) -> dict:
    """Fallback for labels with no curated query above (SessionMetric,
    Treatment, Physio, RehabSession, Outcome, ...) — a capped one-hop
    neighbor pull. Safe because none of these labels have the athlete/
    injury-scale fan-out the curated queries exist to avoid."""
    acc = _Accumulator()

    for record in session.run(
        f"""
        MATCH (n {{id: $id}})-[r]->(m)
        RETURN {_node_return('m')}, type(r) AS rel_type
        LIMIT $limit
        """,
        id=node_id,
        limit=GENERIC_EXPAND_LIMIT,
    ):
        acc.add_node(record)
        acc.add_edge(record["rel_type"], node_id, record["id"])

    for record in session.run(
        f"""
        MATCH (m)-[r]->(n {{id: $id}})
        RETURN {_node_return('m')}, type(r) AS rel_type
        LIMIT $limit
        """,
        id=node_id,
        limit=GENERIC_EXPAND_LIMIT,
    ):
        acc.add_node(record)
        acc.add_edge(record["rel_type"], record["id"], node_id)

    return acc.result()


_EXPANDERS = {
    "Athlete": _expand_athlete,
    "Injury": _expand_injury,
    "Flag": _expand_flag,
}


def expand_node(session, node_id: str) -> dict | None:
    """Looks up the node's label and dispatches to a type-specific query.
    Returns None if no node with this id exists."""
    label = fetch_node_label(session, node_id)
    if label is None:
        return None
    expander = _EXPANDERS.get(label, _expand_generic)
    return expander(session, node_id)


def search_nodes(session, query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive match on Athlete.name / Injury.type / Injury.body_part."""
    rows = session.run(
        f"""
        MATCH (n)
        WHERE (n:Athlete AND toLower(n.name) CONTAINS toLower($q))
           OR (n:Injury AND (toLower(n.type) CONTAINS toLower($q) OR toLower(n.body_part) CONTAINS toLower($q)))
        RETURN {_node_return('n')}
        LIMIT $limit
        """,
        q=query,
        limit=limit,
    ).data()
    return [_node_row(r) for r in rows]


def fetch_nodes_by_ids(session, ids: list[str]) -> list[dict]:
    rows = session.run(
        f"""
        UNWIND $ids AS id
        MATCH (n {{id: id}})
        RETURN {_node_return('n')}
        """,
        ids=ids,
    ).data()
    return [_node_row(r) for r in rows]
