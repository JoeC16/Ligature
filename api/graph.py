"""Cypher for the frontend graph explorer (build order step 7): a small
curated starting view (fetch_overview) plus label-dispatched expansion
(expand_node), so the frontend never has to reason about which
relationships are "the bulk ones" (an Athlete's ~120 Sessions, ~280
WellnessEntries) versus the handful worth surfacing on a click.

Every node returned carries its full property map (for the detail panel);
every edge carries a computed id ("{type}:{from}->{to}", not the
database's internal relationship id, which isn't a stable public
contract) so the frontend can dedupe edges pulled in from more than one
query.
"""

from __future__ import annotations

# Labels with a curated expander below (_EXPANDERS): Athlete, Injury,
# Flag. Anything else (SessionMetric, Treatment, Physio, RehabSession,
# Outcome) falls through to a generic, capped one-hop neighbor expansion.
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


def _enrich_display_names(session, nodes: dict[str, dict]) -> None:
    """Fills in properties['display_name'] for labels whose own properties
    aren't human-readable, so the frontend never has to fall back to a raw
    id like `flag-73hshd738` or `metric-0045`.

    Most labels already carry something legible (Athlete.name, Injury.type,
    Treatment.type, ...) — this only covers the two that don't: a Flag's
    own properties are just confidence/date/resolution_state (what it
    means is "this matches a specific prior injury", which only exists on
    the far end of its MATCHES edge), and a SessionMetric's are just raw
    load numbers (what it means is "this session, this date", which only
    exists on the parent Session one hop up via PRODUCED). One batched
    query per label, keyed off whatever's actually in `nodes` this call —
    callers don't need to know which labels need it."""
    flag_ids = [n["id"] for n in nodes.values() if n["label"] == "Flag"]
    if flag_ids:
        for record in session.run(
            """
            UNWIND $ids AS fid
            MATCH (f:Flag {id: fid})-[:MATCHES]->(i:Injury)
            RETURN fid, i.type AS injury_type
            """,
            ids=flag_ids,
        ):
            props = nodes[record["fid"]]["properties"]
            pct = round((props.get("confidence") or 0) * 100)
            props["display_name"] = f"{pct}% match: {record['injury_type']}"

    metric_ids = [n["id"] for n in nodes.values() if n["label"] == "SessionMetric"]
    if metric_ids:
        for record in session.run(
            """
            UNWIND $ids AS mid
            MATCH (s:Session)-[:PRODUCED]->(m:SessionMetric {id: mid})
            RETURN mid, s.date AS session_date, s.type AS session_type
            """,
            ids=metric_ids,
        ):
            props = nodes[record["mid"]]["properties"]
            session_type = (record["session_type"] or "session").title()
            props["display_name"] = f"{session_type} — {record['session_date']}"


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

    def result(self, session) -> dict:
        _enrich_display_names(session, self.nodes)
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}


def fetch_overview(session) -> dict:
    """Every Athlete, Injury, and Flag, plus the edges between them
    (SUSTAINED, SIMILAR_PATTERN_TO, CURRENTLY, MATCHES). Still none of the
    bulk session/wellness nodes -- those stay behind a click, always.

    Used to curate down to just "athletes with something going on" here,
    server-side -- but on a real squad that's a judgment call (a physio
    might genuinely want to see the whole roster, or just one position),
    and baking it into the query meant the only way to see more was to
    change the backend. That curation moved to the frontend as an actual
    filter panel (default state: roughly this same curated shape) instead
    -- see frontend/app.js. Every Athlete still carries active_flag_count
    when the flagging agent's active for them, whether or not Flag nodes
    themselves are in the client's current filter -- the halo that draws
    doesn't depend on Flag nodes being visible."""
    acc = _Accumulator()

    for record in session.run(
        """
        MATCH (a:Athlete)
        OPTIONAL MATCH (a)-[:CURRENTLY]->(f:Flag)
        RETURN a.id AS id, labels(a)[0] AS label, properties(a) AS properties, count(f) AS flag_count
        """
    ):
        row = _node_row(record)
        if record["flag_count"]:
            row["properties"]["active_flag_count"] = record["flag_count"]
        acc.nodes[row["id"]] = row

    for record in session.run(f"MATCH (n:Injury) RETURN {_node_return('n')}"):
        acc.add_node(record)

    for record in session.run(f"MATCH (n:Flag) RETURN {_node_return('n')}"):
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

    return acc.result(session)


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
        OPTIONAL MATCH (f)-[r:MATCHES]->(i:Injury)
        RETURN {_node_return('f')}, i.id AS matched_injury_id, properties(r) AS match_properties
        """,
        id=athlete_id,
    ):
        acc.add_node(record)
        acc.add_edge("CURRENTLY", athlete_id, record["id"])
        # The matched Injury is already on screen -- fetch_overview now
        # loads every Injury -- this just draws the line connecting a
        # revealed Flag to the specific case it matched, without a second
        # click into the flag itself.
        if record["matched_injury_id"] is not None:
            acc.add_edge("MATCHES", record["id"], record["matched_injury_id"], record["match_properties"])

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

    return acc.result(session)


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

    return acc.result(session)


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

    return acc.result(session)


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

    return acc.result(session)


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
    """Used for /ask's matched_ids and search-result focusing — either can
    legitimately name a Flag or SessionMetric id, so this goes through the
    same accumulator as everything else to get display_name filled in too,
    rather than returning raw rows directly."""
    acc = _Accumulator()
    for record in session.run(
        f"""
        UNWIND $ids AS id
        MATCH (n {{id: id}})
        RETURN {_node_return('n')}
        """,
        ids=ids,
    ):
        acc.add_node(record)
    return list(acc.result(session)["nodes"])
