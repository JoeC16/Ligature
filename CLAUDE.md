# Ligature — Graph-Native Sports Biometric Intelligence

## What this is

Ligature is a graph-native platform for elite sports performance and medical
teams. It ingests the same data existing systems already collect (GPS load,
wellness surveys, injury logs, treatment records) but instead of collapsing
it into a single risk score, it models every session, metric, wellness
entry, treatment, and injury as a node in a graph — so staff can traverse
the actual relationships between them, query them in plain English, and see
which patterns are shared across the whole squad, not just one player's
history.

The core differentiator versus existing tools (Catapult, Zone7, Kitman
Labs — all score-based, black-box) is **explorability and auditability**:
every conclusion the system surfaces links back to the actual graph nodes
that produced it. Nothing is a bare number; everything is a traceable path.

## Product principle — read this before building anything

**The system surfaces evidence. It never prescribes clinical or training
action.**

This is not just a UX choice — directive treatment/training recommendations
risk crossing into medical-device/clinical-decision-support regulatory
territory (e.g. MHRA SaMD classification in the UK). Every feature should
be framed as "here is the pattern, here is who else it matched, here is
what happened before" — never "do X." The physio or sports scientist makes
the call. Keep this constraint in mind for every agent, report, or flag the
system produces.

## Graph schema

### Node types

- `Athlete` — id, position, age, training history
- `Session` — date, type (match/training/gym), intensity, drills
- `SessionMetric` — HSR distance, sprint count, accel/decel load, total
  distance; linked to a specific Session + Athlete
- `WellnessEntry` — sleep hours, sleep quality, HRV, subjective soreness,
  mood; logged daily per Athlete
- `Injury` — type, body part, date of onset, severity, mechanism
- `Treatment` — type (physio session, strapping, massage, injection, rest
  day), date, practitioner, notes
- `RehabSession` — exercise/loading protocol, load prescribed, RPE
  reported, completed vs. planned
- `ClinicalNote` — free text with structured tags extracted (body part,
  severity, practitioner assessment)
- `Cluster` — a derived node representing a detected recurring pattern;
  never raw input, always computed
- `Flag` — a derived node written when an athlete's rolling signature
  matches a known injury-preceding pattern above a confidence threshold

### Key edges (weighted, directional, time-aware — not booleans)

- `(Athlete)-[:PARTICIPATED_IN]->(Session)`
- `(Session)-[:PRODUCED]->(SessionMetric)`
- `(Athlete)-[:REPORTED]->(WellnessEntry)`
- `(Athlete)-[:SUSTAINED]->(Injury)`
- `(SessionMetric)-[:PRECEDED {lag_days, correlation_strength}]->(Injury)`
  — **computed by the pattern engine, never manually entered**
- `(Injury)-[:SIMILAR_PATTERN_TO {shared_metrics, confidence}]->(Injury)`
  — the cross-athlete cluster edge; the core differentiating feature
- `(Physio)-[:ADMINISTERED]->(Treatment)-[:TARGETS]->(Injury)`
- `(Treatment)-[:FOLLOWED_BY {days_gap}]->(RehabSession)`
- `(RehabSession)-[:PRODUCED]->(Outcome)` — outcome is either clean return
  to full training on date X, or re-aggravation on date X
- `(Athlete)-[:CURRENTLY]->(Flag)` — active flags for a player, each tied
  to the specific pattern/confidence that triggered it, with a resolution
  state (reviewed + action taken, or dismissed) written back once a physio
  actions it

## Architecture — four core layers, plus two phase-2 layers

1. **Ingest** — pulls from GPS export/API, wellness survey data, and
   medical/physio injury + treatment logs. No new hardware. Normalize into
   the schema above via a scheduled ETL pipeline. This is the least
   glamorous and most time-consuming part of v1 — plan for messy,
   inconsistent club data.

2. **Graph store** — Neo4j (or Memgraph if in-memory speed matters more
   than tooling maturity). Neo4j preferred early for its visualization
   tooling (Bloom) since the graph itself is part of the product demo, and
   for its Graph Data Science library (similarity/community detection
   algorithms — don't hand-roll this).

3. **Pattern engine** — background job, not computed live per-query. For
   every injury, looks back N days across metrics/wellness for that
   athlete, scores which combinations deviated from *that athlete's own*
   baseline (not population baseline — individual variance matters).
   Clusters injuries across the whole athlete pool by shared deviation
   signature. Writes results back as `PRECEDED` and `SIMILAR_PATTERN_TO`
   edges with confidence scores — queries traverse precomputed edges, they
   never recompute from scratch.

4. **Natural language interrogation** — text-to-Cypher against a fixed,
   known schema (constrain generation to this schema to bound
   hallucination risk). The LLM only translates the question in and the
   graph's actual computed result back out to plain language — it never
   infers or invents a correlation itself. Every answer must link back to
   the underlying nodes so a physio can verify it directly.

### Phase 2

5. **Treatment/rehab input** — structured quick-entry for physios
   (dropdowns + duration + 0-10 outcome field; free text optional, tagged
   via NLP in the background rather than requiring manual categorization).
   Closes the loop: once treatment outcomes are in the graph, you can query
   which treatment protocols actually preceded a clean return to play vs.
   re-injury for a given pattern — data no GPS vendor or physio EMR has on
   its own, because neither holds both sides.

6. **Flagging agent** — scheduled job (nightly, or after each session's
   data lands). For every active athlete: pulls their rolling 7–14 day
   window, compares against precomputed cluster patterns (both the
   athlete's own prior injury signature and cross-squad clusters), and if
   similarity crosses a confidence threshold, writes a `Flag` node tied to
   the specific matched pattern. Report generation then turns the
   structured flag into plain language, always linking back to the
   matched historical case. Two things to build in from the start:
   - **Per-club (possibly per-player) configurable confidence threshold**
     — squads with thin cover need different false-positive tolerance than
     squads with strong depth.
   - **Resolution state on every flag** — physio reviewed + actioned, or
     dismissed as not relevant, written back into the graph. This is the
     long-term asset: ground truth on which flags were real vs. false
     alarms, used later to improve the pattern engine's own confidence
     scoring.

## Build order (don't build top-down)

1. Graph schema + local Neo4j instance, seeded with synthetic test data
2. Ingestion pipeline (start with CSV import — most exports land this way)
3. Pattern engine — run retrospectively on historical/seed data first
4. Treatment/session input — simple internal form or API endpoint, not
   polished UI yet; enough to test the closed-loop query
5. NL query layer — text-to-Cypher, can be prototyped standalone before
   full integration
6. Flagging agent — same discipline as the query layer: structured graph
   traversal first, LLM only for the write-up
7. Frontend graph explorer — deserves real design investment once the
   backend is solid; the clickable, visual graph is the product's "aha"
   moment in any demo

## Go-to-market context (for reference, not build-relevant)

- Target buyer: club medical/performance staff — physios and sports
  scientists who don't trust a black-box red flag and want to see the
  evidence before benching a player.
- Wedge: integrate with data clubs already collect (GPS vendor exports,
  existing wellness apps) rather than competing on hardware.
- Pilot ask: 6–12 months of historical session/wellness/injury data from
  one club, one contact on medical/performance staff, ~3 weeks to a first
  evidence graph — retrospective proof before any long-term commitment.
- Moat: the graph gets more valuable and harder to replicate the longer it
  runs on a club's real data — a competitor starting later is structurally
  behind, not just feature-behind.
