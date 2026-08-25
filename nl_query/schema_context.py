"""The fixed schema description handed to the LLM for text-to-Cypher
generation — CLAUDE.md: "constrain generation to this schema to bound
hallucination risk." Kept accurate to schema/constraints.cypher and every
node/edge property actually written by seed/, ingest/, pattern_engine/,
and api/ — this is the single source of truth the model is allowed to use,
so drift here directly causes bad or hallucinated queries.
"""

SCHEMA_DESCRIPTION = """
You are translating a question about a sports team's graph database into a
single Cypher query for Neo4j. Use ONLY the labels, relationship types, and
properties listed below — nothing else exists in this graph.

NODE TYPES AND THEIR PROPERTIES:
  Athlete          id, name, position, age
  Session          id, date, type ("training" or "match"), intensity, drills
  SessionMetric    id, hsr_distance_m, sprint_count, accel_decel_load, total_distance_m
  WellnessEntry    id, date, sleep_hours, sleep_quality, hrv, soreness, mood
  Injury           id, type, body_part, date, severity, mechanism
  Treatment        id, date, type, practitioner, notes (notes may be absent)
  RehabSession     id, date, protocol, load_prescribed, rpe_reported, completed
  Outcome          id, result ("clean_return" or "re_aggravation"), date
  Physio           id, name
  ClinicalNote     id, text, body_part, severity, assessment
  Cluster          defined in the schema but not yet populated by anything — a
                    query touching it will correctly return zero rows
  Flag             defined in the schema but not yet populated by anything — a
                    query touching it will correctly return zero rows

RELATIONSHIPS (always this direction):
  (Athlete)-[:PARTICIPATED_IN]->(Session)
  (Session)-[:PRODUCED]->(SessionMetric)
  (Athlete)-[:REPORTED]->(WellnessEntry)
  (Athlete)-[:SUSTAINED]->(Injury)
  (SessionMetric)-[:PRECEDED {lag_days, correlation_strength}]->(Injury)
  (Injury)-[:SIMILAR_PATTERN_TO {shared_metrics, confidence}]->(Injury)
  (Injury)-[:HAS_NOTE]->(ClinicalNote)
  (Physio)-[:ADMINISTERED]->(Treatment)
  (Treatment)-[:TARGETS]->(Injury)
  (Treatment)-[:FOLLOWED_BY {days_gap}]->(RehabSession)
  (RehabSession)-[:PRODUCED]->(Outcome)

RULES:
- Generate exactly one read-only Cypher query. Never CREATE, MERGE, SET,
  DELETE, REMOVE, DROP, or use CALL/LOAD CSV — this graph is queried,
  never written to, by this tool.
- Use only the labels, relationship types, and properties listed above. Do
  not invent properties or relationships that aren't listed.
- Dates are stored as ISO strings ("YYYY-MM-DD") — compare them as strings
  or with date() as appropriate.
- If the question cannot be answered with this schema (asks for something
  not modeled, or requires a write), do not guess — say so instead of
  producing a best-effort query.

EXAMPLE QUERIES (real queries already used elsewhere against this exact schema):

  # Which sessions preceded a given injury, and how strongly
  MATCH (m:SessionMetric)-[p:PRECEDED]->(i:Injury {type: 'hamstring strain'})
  RETURN m, p, i

  # Injuries with no treatment logged yet
  MATCH (a:Athlete)-[:SUSTAINED]->(i:Injury)
  WHERE NOT (i)<-[:TARGETS]-(:Treatment)
  RETURN i.id AS id, a.name AS athlete_name, i.type AS type, i.date AS date

  # Which treatment protocols preceded a clean return vs. a re-aggravation
  MATCH (t:Treatment)-[:FOLLOWED_BY]->(r:RehabSession)-[:PRODUCED]->(o:Outcome)
  RETURN r.protocol, o.result, count(*) AS n

  # An athlete's wellness trend
  MATCH (a:Athlete {name: 'Allison Hill'})-[:REPORTED]->(w:WellnessEntry)
  RETURN w.date, w.sleep_quality, w.hrv, w.soreness ORDER BY w.date
""".strip()
