# Ligature

Graph-native sports biometric intelligence. See [CLAUDE.md](./CLAUDE.md) for
the full product/architecture writeup and graph schema.

This repo currently implements **build order steps 1–3**:

1. A local Neo4j instance with the schema as Cypher constraints, seeded with
   one season of realistic synthetic data for 5 athletes — sessions,
   wellness entries, injuries, and treatment/rehab/outcome chains. Two of
   the six injuries (both hamstring strains) have a deliberately engineered
   load spike + wellness dip in the lead-up, as ground truth for step 3.
2. A CSV ingestion pipeline for real (or real-shaped) GPS, wellness, and
   injury exports — the messiest, most time-consuming part per CLAUDE.md,
   so it's built to cope with inconsistent column names, date formats, and
   missing values across three unrelated source systems.
3. A pattern engine that computes `PRECEDED` and `SIMILAR_PATTERN_TO` edges
   for real — for every injury, scores which of that athlete's own metrics
   deviated from *their own* baseline in the lead-up, and clusters injuries
   across the squad by shared deviation signature. Run against the step-1
   seed data, it independently rediscovers the engineered hamstring pattern
   without being told where to look.

## Setup

Requires Docker and Python 3.11+.

```bash
cp .env.example .env          # defaults are fine for local dev
docker compose up -d          # starts Neo4j (Bolt on 7687, browser on 7474)

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python seed/seed_data.py
python pattern_engine/run_pattern_engine.py
```

The seed script applies the schema constraints, wipes any existing graph
data, generates one season of synthetic data, and writes it all in. It's
safe to rerun — generation is seeded, so every run produces identical
data (`generators.SEED`). It loads raw data only: `PRECEDED` and
`SIMILAR_PATTERN_TO` don't exist until you run the pattern engine next.

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
  quality, HRV, soreness) — baked into the raw `SessionMetric`/
  `WellnessEntry` values by `seed/generators.py`. No edges point at it yet;
  that's what the pattern engine is for.

## Compute the pattern engine

`pattern_engine/run_pattern_engine.py` is what actually writes `PRECEDED`
and `SIMILAR_PATTERN_TO` — CLAUDE.md is explicit these are "computed by the
pattern engine, never manually entered," so it's the only thing that writes
them, and it owns them exclusively: every run deletes and recomputes both
edge types from the graph's current state (a scoped delete, not a full
wipe — nothing else is touched), so it's safe to rerun after new data lands.

For every injury it looks back 14 days over *that athlete's own*
`SessionMetric`/`WellnessEntry` history (session-type-segmented baselines
for load metrics, since a match is legitimately harder than training) and
scores deviation as a z-score against that baseline. A single noisy field
crossing threshold isn't rare enough on its own to act on — with ~4 metric
fields per session and 5 wellness fields over a 14-day window, *something*
clears a couple of standard deviations on pure chance often enough to
matter — so it requires at least two fields to co-deviate on the same day,
and for wellness, that same field to reappear on multiple flagged days,
before it counts. `PRECEDED` edges (from the deviating `SessionMetric`,
never `WellnessEntry` — the schema only puts `SessionMetric` on that side)
carry `lag_days` and a `correlation_strength` derived from deviation
magnitude; each injury's full deviating-field set becomes its "signature,"
and every pair of injuries gets a `SIMILAR_PATTERN_TO` edge (Jaccard
overlap of their signatures) once they clear a similarity threshold.

Run against the seed data, it rediscovers the engineered hamstring pattern
exactly — all 6 spiking `SessionMetric` nodes get `PRECEDED` edges to the
right injury, the two hamstring injuries get linked by `SIMILAR_PATTERN_TO`,
and the other 4 injuries (which have no engineered lead-in) get nothing —
without being told in advance which injuries or which sessions to look at.

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

## Ingest real (or real-shaped) data

`ingest/ingest_data.py` is the CSV pipeline — unlike the seed script, it
never wipes anything. It's additive/upsert, meant to run repeatedly (once
per scheduled export) against a graph that's already live, the way a real
club's GPS/wellness/medical exports would land over a season.

```bash
python ingest/ingest_data.py \
  --roster ingest/sample_data/athlete_roster.csv \
  --gps ingest/sample_data/gps_export.csv \
  --wellness ingest/sample_data/wellness_export.csv \
  --injuries ingest/sample_data/injury_log.csv
```

`--gps` / `--wellness` / `--injuries` are each independent and optional —
pass whichever export actually landed. `--roster` is the athlete-identity
anchor and is required whenever any of the others are passed, since none of
the three source systems share an athlete ID with each other.

The bundled `ingest/sample_data/` CSVs are deliberately messy on purpose —
three different header conventions, three different date formats
(`YYYY-MM-DD`, `DD/MM/YYYY`, `12 Jan 2025`), a comma-thousands number, a
sensor dropout (blank value), a resynced duplicate row, an unrecognized
severity value, and one row for an athlete not in the roster (a trialist) —
so running the command above is itself a demonstration of the pipeline
handling exactly the problem CLAUDE.md calls out. The run prints what it
skipped and why; nothing fails silently. Athlete identity is resolved by
normalized name against the roster, so re-running on an updated or corrected
export MERGEs onto the same nodes rather than duplicating them — same for
every node type here (`Session` is keyed on date+type, `SessionMetric` and
`WellnessEntry` on athlete+date, `Injury` on athlete+body part+onset date).

The sample data uses three new athletes (Jordan Price, Priya Kaur, Marcus
Bellamy) rather than the step-1 seed athletes, so it's safe to run this
right after `seed/seed_data.py` with no id collisions — the two are
independent demonstrations sitting in the same graph.

## Layout

```
docker-compose.yml       # local Neo4j (community edition)
.env.example             # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
requirements.txt
schema/
  constraints.cypher      # uniqueness constraints + indexes, one per node type
common/
  db.py                   # connect() / run_constraints() / write_nodes() / write_edges(),
                           #   shared by seed_data.py and ingest_data.py
seed/
  seed_data.py            # wipe-and-reload dev/demo data — entry point, applies schema, loads, prints summary
  generators.py           # synthetic athletes/sessions/metrics/wellness/injuries/treatments
pattern_engine/
  run_pattern_engine.py    # entry point — pulls, scores, deletes old pattern edges, rewrites, prints summary
  queries.py                # Cypher pull layer only — no logic
  engine.py                 # pure computation: baselines, z-scores, PRECEDED + SIMILAR_PATTERN_TO scoring
ingest/
  ingest_data.py           # additive/upsert CLI entry point for real CSV exports
  normalize.py             # date/number/name cleanup, stable_id() hashing shared by every source
  roster.py                # athlete identity resolution (normalized name -> athlete id)
  sources/
    gps.py                 # GPS export -> Session + SessionMetric
    wellness.py             # wellness survey export -> WellnessEntry
    injuries.py             # injury log export -> Injury
  sample_data/              # deliberately messy sample CSVs, see "Ingest" above
```

## Notes

- The Graph Data Science plugin isn't enabled yet. The pattern engine's
  `PRECEDED`/`SIMILAR_PATTERN_TO` scoring is plain Python (pairwise, over
  6 seeded injuries — GDS would be overkill at this scale). GDS is still
  earmarked for later: materializing `Cluster` nodes via real community
  detection once there's enough `SIMILAR_PATTERN_TO` density for that to
  mean something. See the comment in `docker-compose.yml` for where to add
  the plugin when that's built. `Cluster` and `Flag` both stay unpopulated
  for now (constrained in the schema, no writer yet).
- `Physio` and `Outcome` node types are declared in `schema/constraints.cypher`
  even though CLAUDE.md's "Node types" list doesn't name them — both are
  referenced as edge endpoints in CLAUDE.md's "Key edges" section
  (`Physio-[:ADMINISTERED]->Treatment`, `RehabSession-[:PRODUCED]->Outcome`),
  so minimal node types were added for the seed data to attach to.
