#!/bin/bash
# Runs once, at image build time (invoked by the root Dockerfile after the
# venv + app code are in place) -- generates the full synthetic season
# against a throwaway Memgraph instance, computes the pattern engine's
# edges and the flagging agent's flags against it, snapshots the result,
# and shuts that instance down.
#
# The snapshot this leaves at /app/seed-snapshot becomes part of the
# image. entrypoint.sh copies it into Memgraph's real data directory
# before the container's own Memgraph starts, so a cold start recovers an
# already-complete graph in the time it takes to load a snapshot file --
# not the multi-minute CPU cost of regenerating ~25k nodes/edges from
# scratch on Render's free-tier 0.1 vCPU on every single boot, which is
# what made the graph render empty for the first couple of minutes after
# a deploy. The synthesis is deterministic (seed/generators.py's own
# SEED), so baking it once here produces exactly the same demo graph a
# runtime re-seed always did -- nothing about what a visitor sees changes,
# only when the cost of producing it is paid: once, during `docker build`
# (which isn't racing a health-check timeout the way container boot is),
# instead of on every container start.
#
# --memory-limit matches entrypoint.sh's runtime value on purpose -- a
# dataset that only fits because the build host happens to have more RAM
# than the real 512MB instance would be a problem discovered in
# production, not here.

set -euo pipefail

export PYTHONUNBUFFERED=1

DATA_DIR=/app/seed-snapshot

echo "[build-seed] Starting a throwaway Memgraph instance..."
/usr/lib/memgraph/memgraph \
    --data-directory="${DATA_DIR}" \
    --memory-limit=250 \
    --bolt-address=127.0.0.1 \
    --monitoring-address=127.0.0.1 \
    --metrics-address=127.0.0.1 &
MEMGRAPH_PID=$!

echo "[build-seed] Waiting for it to accept connections..."
python3 deploy/huggingface/wait_for_bolt.py

echo "[build-seed] Seeding demo data..."
python seed/seed_data.py

echo "[build-seed] Running the pattern engine..."
python pattern_engine/run_pattern_engine.py

# No --as-of needed: seed/generators.py plants a load-spike + wellness-dip
# echo (same signature as the hamstring cluster) in the final ~12 days of
# every athlete's own generated data, so the default per-athlete reference
# date (their own latest data + 1 day) already lands inside it -- a
# visitor gets real Flags without this depending on a hand-picked
# calendar date staying valid as the season's date range changes.
echo "[build-seed] Running the flagging agent..."
python flagging_agent/run_flagging_agent.py

# One well-known, intentionally public login so a visitor can actually see
# the demo now that every /api/* route requires a session -- this account
# reaches nothing but the synthetic season above, so there's no real data
# for a public password to expose. Credentials are documented in
# deploy/huggingface/README.md and deploy/render/README.md -- keep both in
# sync with the values below if either changes.
echo "[build-seed] Creating the demo login..."
python auth/create_user.py \
    --email demo@ligature.app \
    --name "Demo Account" \
    --password ligature-demo

echo "[build-seed] Writing a snapshot..."
python3 -c "
import os
from neo4j import GraphDatabase

uri = os.environ.get('GRAPH_DB_URI', 'bolt://localhost:7687')
user = os.environ.get('GRAPH_DB_USER', 'memgraph')
password = os.environ.get('GRAPH_DB_PASSWORD', 'unused')

driver = GraphDatabase.driver(uri, auth=(user, password))
with driver.session() as session:
    # .single() forces the driver to wait for the server's actual result
    # row (CREATE SNAPSHOT returns the written file's path) instead of a
    # lazy, unconsumed result -- the file must already be complete on disk
    # for the server to know that path, so consuming this result is what
    # makes the snapshot below-us-safe-to-copy guarantee actually hold.
    record = session.run('CREATE SNAPSHOT;').single()
    print('Snapshot written:', record[0] if record else '(no path returned)')
driver.close()
"

# SIGTERM + wait, not kill -9: a clean shutdown flushes/releases whatever
# Memgraph needs to before the data directory below is safe to copy out
# of this container and into a fresh one -- the same guarantee a real
# restart relies on for its own durability. `wait` on a process that
# exited via a signal reports a 128+signal exit status, not 0 -- under
# `set -e` that reads as this script failing right after the intended,
# successful shutdown, so its result is deliberately swallowed here
# rather than left to abort the build on an expected exit code.
echo "[build-seed] Stopping Memgraph..."
kill -TERM "${MEMGRAPH_PID}"
wait "${MEMGRAPH_PID}" || true

echo "[build-seed] Done -- baked snapshot at ${DATA_DIR}"
