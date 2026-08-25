# Ligature

Graph-native sports biometric intelligence. See [CLAUDE.md](./CLAUDE.md) for
the full product/architecture writeup and graph schema.

This repo currently implements **build order step 1**: a local Neo4j
instance with the schema as Cypher constraints, seeded with one season of
realistic synthetic data for 5 athletes — sessions, wellness entries,
injuries, treatment/rehab/outcome chains, and a worked example of the
hamstring injury pattern CLAUDE.md's pattern engine section describes.

## Setup

Requires Docker and Python 3.11+.

```bash
cp .env.example .env          # defaults are fine for local dev
docker compose up -d          # starts Neo4j (Bolt on 7687, browser on 7474)

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python seed/seed_data.py
```

The seed script applies the schema constraints, wipes any existing graph
data, generates one season of synthetic data, and writes it all in. It's
safe to rerun — generation is seeded, so every run produces identical
data (`generators.SEED`).

Neo4j Browser: http://localhost:7474 (user `neo4j`, password from `.env`).

## What gets seeded

- 5 athletes, one ~40-week season (Aug–May), 3 GPS-tracked sessions/week
  (2x training + 1x match) plus a weekly gym session, and daily wellness
  entries — all generated around a **per-athlete baseline** with noise,
  per CLAUDE.md's "individual variance matters, not population baseline"
  principle.
- 6 injuries across the squad, 3 with full treatment → rehab → outcome
  chains (one re-aggravation, two clean returns — deliberately different
  outcomes for the same injury type, since that contrast is the point of
  closing the treatment-outcome loop later).
- **The hamstring pattern**: athlete-1 and athlete-2 each sustain a
  hamstring strain preceded by 8 days of load spiking against their own
  baseline (HSR distance, accel/decel load) and wellness dipping (sleep
  quality, HRV, soreness). `PRECEDED` edges link the spiking
  `SessionMetric` nodes to each injury; a `SIMILAR_PATTERN_TO` edge links
  the two injuries.

  **Important**: CLAUDE.md is explicit that `PRECEDED` and
  `SIMILAR_PATTERN_TO` are normally *computed by the pattern engine*
  (build order step 3), never manually entered. That engine doesn't exist
  yet, so `seed/hamstring_pattern.py` hand-writes this one example so
  there's something concrete to query. It's a fixture, not a general
  algorithm — it labels a spike that `seed/generators.py` generated on
  purpose, it doesn't detect one.

## Explore it

A few queries to paste into Neo4j Browser:

```cypher
// The hamstring lead-up: which sessions preceded which injury, and how strongly
MATCH (m:SessionMetric)-[p:PRECEDED]->(i:Injury {type: 'hamstring strain'})
RETURN m, p, i
```

```cypher
// The cross-athlete cluster edge — the core differentiating feature
MATCH (i1:Injury)-[s:SIMILAR_PATTERN_TO]->(i2:Injury)
RETURN i1, s, i2
```

```cypher
// Full traceable path for one athlete: sessions -> metrics -> injury -> treatment -> outcome
MATCH (a:Athlete {id: 'athlete-1'})-[:SUSTAINED]->(i:Injury)
OPTIONAL MATCH (m:SessionMetric)-[:PRECEDED]->(i)
OPTIONAL MATCH (t:Treatment)-[:TARGETS]->(i)
OPTIONAL MATCH (t)-[:FOLLOWED_BY]->(r:RehabSession)-[:PRODUCED]->(o:Outcome)
RETURN a, i, m, t, r, o
```

```cypher
// An athlete's wellness trend around their injury date
MATCH (a:Athlete {id: 'athlete-1'})-[:REPORTED]->(w:WellnessEntry)
RETURN w.date, w.sleep_quality, w.hrv, w.soreness ORDER BY w.date
```

## Layout

```
docker-compose.yml       # local Neo4j (community edition)
.env.example             # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
requirements.txt
schema/
  constraints.cypher      # uniqueness constraints + indexes, one per node type
seed/
  seed_data.py            # entry point — connects, applies schema, wipes, loads, prints summary
  generators.py           # synthetic athletes/sessions/metrics/wellness/injuries/treatments
  hamstring_pattern.py     # the one hand-authored PRECEDED / SIMILAR_PATTERN_TO example
```

## Notes

- The Graph Data Science plugin isn't enabled yet — it's not needed until
  the pattern engine (build order step 3) does real similarity/community
  detection. See the comment in `docker-compose.yml` for where to add it.
- `Physio` and `Outcome` node types are declared in `schema/constraints.cypher`
  even though CLAUDE.md's "Node types" list doesn't name them — both are
  referenced as edge endpoints in CLAUDE.md's "Key edges" section
  (`Physio-[:ADMINISTERED]->Treatment`, `RehabSession-[:PRODUCED]->Outcome`),
  so minimal node types were added for the seed data to attach to.
