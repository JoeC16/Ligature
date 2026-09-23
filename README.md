---
title: Ligature
emoji: 🕸️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Ligature

Graph-native sports biometric intelligence. See [CLAUDE.md](./CLAUDE.md) for
the full product/architecture writeup and graph schema.

> **Live demo**: this repo can deploy itself to a free public URL — see
> [deploy/render/README.md](./deploy/render/README.md) (currently the free
> path; no credit card, deploys straight from this GitHub repo, the root
> `Dockerfile` bundling Memgraph + the app in one container) or
> [deploy/huggingface/README.md](./deploy/huggingface/README.md) (Hugging
> Face Spaces — free until a July 2026 policy change, now needs a paid PRO
> plan for a Docker Space; the frontmatter above is Spaces' own config
> format in case you go that route, harmless everywhere else). Local dev
> runs on Memgraph too (below) — see CLAUDE.md's "Graph store" note for
> why this moved off Neo4j.
> Everything below this point is the normal project docs.

This repo currently implements **all 7 build order steps**:

1. A local Memgraph instance with the schema as Cypher constraints, seeded with
   one season of realistic synthetic data for a 30-player squad — sessions,
   wellness entries, injuries, and treatment/rehab/outcome chains across a
   deliberate mix of injury-free, injured-and-returned, and still-injured/
   ongoing-rehab scenarios. Five of the injuries (all hamstring strains, a
   real cross-athlete cluster) have a deliberately engineered load spike +
   wellness dip in the lead-up, as ground truth for step 3.
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
4. A small FastAPI app for physios to log `Treatment` → `RehabSession` →
   `Outcome` — structured quick-entry, dropdowns via Swagger UI, closing
   the loop CLAUDE.md describes: which treatment protocols actually
   preceded a clean return versus a re-aggravation for a given pattern.
5. A text-to-Cypher NL query layer — a standalone CLI prototype (per
   CLAUDE.md's own phasing, not wired into the API yet) that translates a
   plain-English question into a read-only Cypher query against the fixed
   schema, runs it, and explains the exact results back in plain language.
   The first LLM integration in the repo — see its own section below for
   the safety properties that come with that.
6. A flagging agent — for every athlete, compares their current rolling
   window against every prior injury's now-persisted deviation signature
   (both their own past injuries and the rest of the squad's, which turns
   out to be one comparison, not two), and writes a `Flag` when one clears
   a per-athlete confidence threshold. Run with no arguments at all against
   the seed data (the default per-athlete reference date is all it needs —
   the seed data plants a real echo of the hamstring cluster's signature at
   the end of five injury-free athletes' own data), it flags all five
   against the already-scored hamstring cluster — the predictive half of
   the product, not just the retrospective half step 3 built. Resolution
   write-back (CLAUDE.md's other build-in-from-the-start requirement)
   reuses the step-4 API.
7. A frontend graph explorer — vanilla HTML/CSS/JS, no build step, served
   directly by `api/app.py` so `uvicorn api.app:app` is the one command
   that runs the whole product. A curated starting view (every `Athlete`,
   `Injury`, `Flag`, and the edges between them — never the bulk
   `Session`/`WellnessEntry` nodes), click-to-expand that dispatches on the
   clicked node's label to pull in exactly what's relevant, search, and —
   the NL query layer's "full integration" CLAUDE.md deferred to "whenever
   the frontend arrives" — an ask-in-English box wired straight into
   step 5's pipeline, with any ids in the answer's result rows fetched and
   highlighted on the graph.

## Setup

Requires Docker and Python 3.11+.

```bash
cp .env.example .env          # then fill in SESSION_SECRET -- see below
docker compose up -d          # starts Memgraph (Bolt on 7687, Lab UI on 3000)

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python seed/seed_data.py
python pattern_engine/run_pattern_engine.py
```

`.env` needs one thing filled in before the app will start:
`SESSION_SECRET`, a random value that signs the login session cookie (see
"Log in" below) — `python -c "import secrets; print(secrets.token_hex(32))"`.
Also uncomment `COOKIE_SECURE=false` in `.env` for local dev — cookies are
Secure (HTTPS-only) by default, which is right for a real deploy but means
your browser silently drops the login cookie over plain `http://localhost`.

The seed script applies the schema constraints, wipes any existing graph
data, generates one season of synthetic data, and writes it all in. It's
safe to rerun — generation is seeded, so every run produces identical
data (`generators.SEED`). It loads raw data only: `PRECEDED` and
`SIMILAR_PATTERN_TO` don't exist until you run the pattern engine next.

Memgraph Lab: http://localhost:3000 — connect using host `memgraph`
(the compose service name; use `localhost` if running Lab outside
Docker) and port `7687`. No username/password: Memgraph's community
build (what `docker-compose.yml` runs) doesn't enforce authentication.

## Log in

Every `/api/*` route (everything except `/health` and the static frontend
files) requires a login session — see `api/app.py`'s `require_auth`. This
is app-level auth, unrelated to Memgraph's own (nonexistent) database
auth above: real athlete data reaching this app is the thing being
protected, not the graph database it happens to be stored in.

There's no self-serve signup — CLAUDE.md's go-to-market model is one
pilot club at a time with white-glove setup, not a public product with
accounts anyone can create. Create the first login with:

```bash
python auth/create_user.py --email you@example.com --name "Your Name"
```

Prompts for a password (not echoed, never left in shell history). Run it
again for each additional staff member. Then log in at
http://localhost:8000/login.html once the app is running (see "Log a
treatment" and "The graph explorer" below for `uvicorn api.app:app`).

**Isolation model**: this app has no multi-tenant data model — every
account created against a given database sees that database's whole
graph, with nothing scoping one club's data from another's. That's
deliberate, not an oversight: Memgraph's community build has no
multi-tenancy (isolated per-tenant databases are an Enterprise-only
feature), so real isolation between clubs means **one deployed instance
per club**, each with its own Memgraph and its own accounts — not one
shared app serving many clubs. See `deploy/render/README.md` /
`deploy/huggingface/README.md` for the public single-tenant demo (an
intentionally public demo login, no real data ever); a real pilot deploy
needs its own separate instance, its own `SESSION_SECRET`, and real
accounts created with the command above — never the demo's.

## What gets seeded

- A 30-player squad (realistic position mix — 2 keepers, 5 centre-backs,
  5 fullbacks, 8 midfielders, 5 wingers, 5 strikers), one ~40-week season
  (Aug–May), 3 GPS-tracked sessions/week (2x training + 1x match) plus a
  weekly gym session, and daily wellness entries for every player — all
  generated around a **per-athlete baseline** with noise, per CLAUDE.md's
  "individual variance matters, not population baseline" principle.
- A deliberate mix of three scenarios across the squad: **12 athletes
  injury-free** all season, **12 injured and returned** (a full
  treatment → multi-session rehab → outcome chain each — 9 clean returns,
  3 re-aggravations), and **6 still injured with an ongoing rehab
  program** (a treatment and rehab series with no `Outcome` yet — that's
  what "still in rehab" means in this graph). Those six are themselves
  staggered across the pipeline — one injury with no treatment logged yet,
  one treated but rehab not started, three at increasing points into an
  active program — so `GET /api/injuries/open`, `/api/treatments/open`, and
  `/rehab-sessions/open` all have something real behind them (see "Log a
  treatment" below).
- **The hamstring cluster**: 5 athletes (athlete-1 through athlete-5) each
  sustain a hamstring strain preceded by 8 days of load spiking against
  their own baseline (HSR distance, accel/decel load) and wellness dipping
  (sleep quality, HRV, soreness) — baked into the raw `SessionMetric`/
  `WellnessEntry` values by `seed/generators.py`. A real cross-athlete
  cluster, not an isolated pair, spanning every outcome this graph can
  represent: athlete-1 (Allison Hill) is rushed back and re-aggravates,
  athlete-2 through athlete-4 return clean, and athlete-5 is still mid-
  rehab. No edges point at any of this yet; that's what the pattern
  engine is for.
- **The flagging echo**: 5 of the 12 injury-free athletes carry the same
  load-spike + wellness-dip signature as the hamstring cluster in the
  final ~12 days of the season, with no injury following — "currently
  fine, but showing the same pattern that led to a hamstring strain
  elsewhere in the squad." This is what the flagging agent's default run
  (see "Flag athletes at risk" below) is meant to catch.

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
carry `lag_days`, a `correlation_strength` derived from deviation
magnitude, and — so the ask-in-English answer can explain *why*, not just
*which* — `deviating_fields`/`deviating_zscores`/`baseline_means`/
`baseline_stds`, parallel arrays naming each elevated field, its z-score,
and that specific athlete's own baseline mean/std it was compared against
(never a population or clinical benchmark); each injury's full deviating-field set becomes its "signature,"
and every pair of injuries gets a `SIMILAR_PATTERN_TO` edge (Jaccard
overlap of their signatures) once they clear a similarity threshold.

Run against the seed data, it rediscovers the engineered hamstring cluster
exactly — every spiking `SessionMetric` node gets a `PRECEDED` edge to the
right injury, all 5 hamstring injuries get pairwise-linked by
`SIMILAR_PATTERN_TO` (10 edges — every pair in the cluster), and the other
13 injuries (which have no engineered lead-in) get nothing — without being
told in advance which injuries or which sessions to look at.

It also writes each injury's signature — which fields deviated — onto the
`Injury` node itself as `deviating_fields`. Step 3 only ever needed that
signature in memory to build `SIMILAR_PATTERN_TO`; the flagging agent
(next) needs it persisted, to compare a live athlete's current window
against.

## Flag athletes at risk

`flagging_agent/run_flagging_agent.py` is CLAUDE.md's step 6: for every
athlete, score their current rolling window the same way the pattern
engine scores an injury's lead-up, then compare that signature against
every prior injury's `deviating_fields` — the athlete's own past injuries
and every other athlete's compare identically, which is what makes
CLAUDE.md's "own prior injury signature" and "cross-squad clusters" fall
out of one loop rather than two. A match clearing the athlete's confidence
threshold writes a `Flag`, `(Athlete)-[:CURRENTLY]->(Flag)-[:MATCHES]->
(Injury)` — the specific historical case it matched, always traceable.

**The two things CLAUDE.md says to build in from the start:**
- **Per-player configurable threshold** — an optional `flag_threshold`
  property on `Athlete` (falls back to a default if unset):
  `MATCH (a:Athlete {id: 'athlete-3'}) SET a.flag_threshold = 0.3`
- **Resolution state on every flag** — `unreviewed` by default, written
  back once a physio reviews it. Reuses the step-4 API:
  `GET /api/flags/unreviewed` to see what needs review, `POST
  /api/flags/{id}/resolve` (`resolution_state`: `actioned` or `dismissed`) to
  close it out. That resolution history is the point per CLAUDE.md — "the
  long-term asset: ground truth on which flags were real vs. false
  alarms."

**Reference date matters here.** Default is per-athlete — their own most
recent data date + 1 day, like a real nightly job:

```bash
python pattern_engine/run_pattern_engine.py   # persists all 5 hamstring signatures first
python flagging_agent/run_flagging_agent.py
```

Run this way against the *full* seeded season, expect real flags: the seed
data (`seed/generators.py`) deliberately plants a load-spike + wellness-dip
echo — the same signature as the hamstring cluster — in the final ~12 days
of five injury-free athletes' own data, so their own "most recent data + 1
day" reference date already lands inside it. Each of those five gets
flagged against all 5 hamstring-cluster injuries, at confidence 0.86–1.0 —
the predictive version of the story step 3 told retrospectively: the graph
surfaces this pattern *before* an injury happens, not just explains it
after one already has. `--as-of YYYY-MM-DD` still exists to evaluate the
squad as of an arbitrary earlier point (e.g. testing that the *rest* of
the squad correctly gets nothing at some random mid-season date).

## Explore it

A few queries to paste into Memgraph Lab:

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

## Ask it in English

`nl_query/ask.py` is CLAUDE.md's step 5 — text-to-Cypher against the fixed
schema above. It started as a standalone CLI prototype, per CLAUDE.md's own
phasing ("can be prototyped standalone before full integration"), and as of
step 7 is also wired into `api/app.py`'s `POST /api/ask` — the graph explorer's
ask-in-English box calls the same `ask()` pipeline function this CLI does,
just returning a structured result instead of printing one. This is the
first place an LLM enters the system, so it needs your own key:

```bash
# add to .env: ANTHROPIC_API_KEY=sk-ant-...
python nl_query/ask.py "which injuries have no treatment logged yet?"
python nl_query/ask.py "which treatment protocols preceded a clean return vs. a re-aggravation?"
python nl_query/ask.py "what happened to Allison Hill's sleep quality before her hamstring strain?"
```

Each question goes through: **translate** (Claude turns the question into
Cypher, constrained to the exact schema in `nl_query/schema_context.py` —
CLAUDE.md: "constrain generation to this schema to bound hallucination
risk"; if the question can't be answered with this schema, it says so
instead of guessing) → **guard** (a read-only keyword check) → **execute**
(inside a read-only transaction — the server itself, not just the guard,
rejects a write) → **explain** (a second Claude call, shown only the exact
rows the query returned, instructed to state only what they show). The
output is the plain-language answer, then the Cypher that was actually run
and its raw result rows underneath — CLAUDE.md: "every answer must link
back to the underlying nodes so a physio can verify it directly."

**Two things this tool never does**, both enforced in code, not just
prompted: it never writes to the graph (a write-keyword check before
anything is sent to the database, then the query still runs inside a
read-only transaction that would itself reject a write), and it
never answers from the model's own knowledge — the explanation step is
only ever shown the literal rows the query returned.

## Log a treatment (close the loop)

`api/app.py` is a small FastAPI app for physios to log `Treatment` →
`RehabSession` → `Outcome` — CLAUDE.md's build-order step 4 ("simple
internal form or API endpoint, not polished UI yet; enough to test the
closed-loop query"). It also serves step 6's flag review endpoints
(`GET /api/flags/unreviewed`, `POST /api/flags/{id}/resolve`) — see "Flag athletes
at risk" above — and, as of step 7, the graph explorer itself at `/`.

```bash
uvicorn api.app:app --reload
```

Every `/api/*` route requires a login session (see "Log in" above) —
Swagger UI's own "Try it out" still needs a real browser session cookie to
get past it, same as any other client, so log in at
http://localhost:8000/login.html in the same browser first.

Open **http://localhost:8000/docs** — Swagger UI renders every dropdown
field (treatment type, outcome result, the 0–10 RPE field) as a real form
control, so there's no separate UI to build for this step. The three POSTs
mirror the real workflow: `POST /api/treatments` targets an open injury (see
`GET /api/injuries/open`) and a physio (`GET /api/physios`); `POST /api/rehab-sessions`
follows an open treatment (`GET /api/treatments/open`); `POST /api/outcomes`
closes out an open rehab session (`GET /api/rehab-sessions/open`). Each POST
checks its referenced ids exist first (404, not a silently-empty write),
and Pydantic rejects a bad payload (wrong enum, RPE outside 0–10, a rehab
date before its treatment) with 422 before the database is ever touched.

The seed data already has treatment chains for 17 of the 18 injuries —
`GET /api/injuries/open` finds the one that doesn't yet
(`injury-athlete14-ankle`, freshly sustained and not yet seen by a
physio), and `GET /api/treatments/open` / `GET /api/rehab-sessions/open` find a
few more still mid-pipeline (a treatment with no rehab session logged
yet, and rehab chains still awaiting their final outcome) to practice
closing out. Once you have, this is the closed-loop query CLAUDE.md
describes — which protocols actually preceded a clean return versus a
re-aggravation:

```cypher
MATCH (t:Treatment)-[:FOLLOWED_BY]->(r:RehabSession)-[:PRODUCED]->(o:Outcome)
RETURN r.protocol, o.result, count(*) AS n
ORDER BY r.protocol, o.result
```

**Scope note**: `notes` on `Treatment` is stored as plain text — CLAUDE.md's
phase-2 description also mentions free text "tagged via NLP in the
background" into a `ClinicalNote`, but that's deferred to when the NL
query layer (step 5) brings LLM plumbing into the repo; building it here
would be getting ahead of the pattern this project has followed at every
step (structured traversal first, LLM only where CLAUDE.md actually calls
for one).

## The graph explorer (frontend)

CLAUDE.md's final build-order step — "the clickable, visual graph is the
product's 'aha' moment in any demo." Vanilla HTML/CSS/JS, no bundler, no
build step (consistent with the rest of the repo: stdlib-heavy Python,
FastAPI with no templating layer, Swagger UI as step 4's "form"), served
by the same `api/app.py` process:

```bash
uvicorn api.app:app --reload
```

Open **http://localhost:8000/**. The starting view is deliberately small —
every `Athlete` with something going on (an `Injury` or a `Flag`) plus
every `Injury`, and the edges between them. Not every `Athlete` (most of a
real squad has nothing to show) and no `Flag` nodes at all: the flagging
agent writes one `Flag` per matched historical injury by design, so an
at-risk athlete matching the hamstring cluster is 5 separate `Flag` nodes,
not one — dumping all of that into the first screen defeats the point of
a curated starting view. A flagged athlete instead carries the same calm
halo a `Flag` node gets, directly on itself.

Naively expanding an athlete would pull in a season's worth of `Session`
and `WellnessEntry` nodes at once, so `GET /api/graph/expand/{id}` dispatches
on the clicked node's label to a curated, type-specific query instead:
clicking an athlete surfaces their injuries, their actual `Flag` nodes
(now connected straight to the injury each one matched), and only the
`SessionMetric`s that actually precede one of those injuries (never the
full training log); clicking an injury surfaces its `PRECEDED` sources,
`SIMILAR_PATTERN_TO` links, and treatment → rehab → outcome chain, if any.
Anything else the backend doesn't have a curated query for falls back to a
capped one-hop neighbor pull — safe, since none of those labels have the
athlete/injury-scale fan-out the curated queries exist to avoid.

Drag a node to reposition it, scroll to zoom, drag the background to pan.
Click a node or edge to open its full property map in the side panel.
Search matches athlete names and injury type/body part. The ask-in-English
box at the top is `nl_query/ask.py` wired straight in (see "Ask it in
English" above) — its answer's underlying Cypher and raw rows show in the
side panel, and any node ids in those rows get fetched and highlighted on
the graph if they aren't already on screen, so an answer is never just
text to take on faith.

## Ingest real (or real-shaped) data

`ingest/ingest_data.py` is the CSV pipeline — unlike the seed script, it
never wipes anything. It's additive/upsert, meant to run repeatedly (once
per scheduled export) against a graph that's already live, the way a real
club's GPS/wellness/medical exports would land over a season. There's also
a browser upload page at http://localhost:8000/ingest.html (`POST
/api/ingest`, once logged in — see "Log in" above) driving the exact same
`run_ingest()` pipeline underneath, for someone who'd rather drag in files
than run a CLI command.

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
docker-compose.yml       # local Memgraph (memgraph-platform: DB + Lab UI + MAGE algorithms)
Dockerfile                # bundled Memgraph (bare, no Lab/MAGE) + app image, for the free-tier deploy
.env.example             # GRAPH_DB_URI / GRAPH_DB_USER / GRAPH_DB_PASSWORD / ANTHROPIC_API_KEY /
                          #   SESSION_SECRET / COOKIE_SECURE
requirements.txt
schema/
  constraints.cypher      # uniqueness constraints + indexes, one per node type (Memgraph DDL) --
                           #   includes User, the app's own login/auth infrastructure (see auth/)
auth/
  users.py                # bcrypt hash/verify, create_user() / get_user_by_id() / verify_password()
  create_user.py           # CLI entry point — creates one login, prompts for a password (getpass)
deploy/
  render/README.md        # free-tier deploy: Render + the bundled Dockerfile
  huggingface/README.md    # same Dockerfile on HF Spaces — needs a paid plan there now
  huggingface/build_seed.sh # build-time only: seed -> pattern engine -> flagging agent -> snapshot
  huggingface/entrypoint.sh # shared runtime entrypoint for both: restore baked snapshot -> start DB -> app
  huggingface/wait_for_bolt.py # shared "poll until Memgraph accepts Bolt" loop, used by both scripts above
common/
  db.py                   # connect() / run_constraints() / write_nodes() / write_edges(),
                           #   shared by seed_data.py, ingest_data.py, and the API
api/
  app.py                   # FastAPI app + routes — physio quick-entry for Treatment/RehabSession/Outcome,
                            #   flag review (GET /api/flags/unreviewed, POST /api/flags/{id}/resolve),
                            #   graph explorer routes + POST /api/ask, login routes, and the frontend/ static mount
  schemas.py                # Pydantic request/response models (dropdowns, 0-10 RPE bound, graph node/edge shape)
  reads.py                   # Cypher for the "what's still open" GET endpoints + unreviewed flags
  writes.py                   # Cypher writes, reuses common/db.py
  graph.py                    # Cypher for the graph explorer — curated overview + label-dispatched expand/search/nodes
seed/
  seed_data.py            # wipe-and-reload dev/demo data — entry point, applies schema, loads, prints summary
  generators.py           # synthetic athletes/sessions/metrics/wellness/injuries/treatments
pattern_engine/
  run_pattern_engine.py    # entry point — pulls, scores, deletes old pattern edges, rewrites,
                            #   persists deviating_fields onto each Injury, prints summary
  queries.py                # Cypher pull layer only — no logic
  engine.py                 # pure computation: baselines, z-scores, PRECEDED + SIMILAR_PATTERN_TO scoring,
                             #   compute_signature_at() + jaccard() are reused by flagging_agent/
flagging_agent/
  run_flagging_agent.py    # entry point, --as-of optional — pull -> compute -> write Flag/CURRENTLY/MATCHES
  fetch.py                   # fetch_athletes/fetch_injury_signatures; reuses pattern_engine/queries.py
                              #   for per-athlete metric/wellness history rather than duplicating it
                              #   (named fetch.py, not queries.py — see its own docstring for why)
  agent.py                     # pure computation: per-athlete flag matching against prior signatures
frontend/
  index.html               # header (search, ask-in-english, filters), graph canvas, detail panel, legend
  ingest.html                # browser upload page for ingest/ingest_data.py's pipeline (POST /api/ingest)
  login.html                   # email + password form, POST /api/auth/login
  style.css                     # design tokens (paper/ink/pitch + per-node-type colors), light+dark mode
  graph.js                       # force-directed render + interactions: drag, pan/zoom, tap-to-select
  api.js                           # fetch() wrappers for /api/* -- redirects to login.html on any 401
  app.js                             # wires load-overview -> click-to-expand -> search -> ask -> filters
  ingest.js                           # wires the upload form -> POST /api/ingest -> per-source report
  login.js                             # wires the login form -> POST /api/auth/login -> redirect
nl_query/
  ask.py                   # ask() is the shared translate -> guard -> execute -> explain pipeline
                            #   (returns a result dict; the CLI's print_result() is the only thing that prints)
  schema_context.py         # the fixed schema description given to the LLM (the hallucination-risk bound)
  translator.py              # question -> Cypher (Claude, structured output)
  guard.py                    # pure function — read-only keyword check, the first of two write-blocking layers
  executor.py                  # runs Cypher inside a read-only transaction — the second layer
  responder.py                  # (question, cypher, rows) -> plain-language answer, shown only the real rows
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

- MAGE (Memgraph's graph-algorithms library, bundled in the
  `memgraph-platform` image `docker-compose.yml` uses for local dev)
  isn't used yet. The pattern engine's `PRECEDED`/`SIMILAR_PATTERN_TO`
  scoring is plain Python (pairwise, over 6 seeded injuries — a real
  algorithms library would be overkill at this scale). It's still
  earmarked for later: materializing `Cluster` nodes via real community
  detection once there's enough `SIMILAR_PATTERN_TO` density for that to
  mean something. `Cluster` stays unpopulated for now (constrained in the
  schema, no writer yet) — `Flag` is populated, by
  `flagging_agent/run_flagging_agent.py` (step 6).
- `Physio` and `Outcome` node types are declared in `schema/constraints.cypher`
  even though CLAUDE.md's "Node types" list doesn't name them — both are
  referenced as edge endpoints in CLAUDE.md's "Key edges" section
  (`Physio-[:ADMINISTERED]->Treatment`, `RehabSession-[:PRODUCED]->Outcome`),
  so minimal node types were added for the seed data to attach to.
