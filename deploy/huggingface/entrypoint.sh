#!/bin/bash
# Container entrypoint for the bundled free-tier deploy (see ../../Dockerfile
# -- shared by both deploy/render/README.md and deploy/huggingface/README.md).
# Starts Memgraph in the background, waits for it to accept connections,
# (re)seeds the demo data -- safe and idempotent, since seed_data.py always
# wipes+reloads deterministically and the pattern engine's own edges are a
# scoped delete+recompute -- then serves the app in the foreground.
#
# Re-seeding on every container start isn't a workaround, it's the right
# behavior here: a free host's storage is ephemeral (a restart can wipe
# /data), and this repo's seed data is fully synthetic and reproducible,
# so "re-seed on boot" just means every visitor sees the same known-good
# demo graph regardless of when the container last restarted.

set -euo pipefail

# --memory-limit is in MB. Render's free instance is 512MB total, shared
# with the Python process started below -- Memgraph itself is far lighter
# than Neo4j's JVM (no class metadata, thread-per-connection stacks, or
# off-heap Netty buffers to budget for), so this is a generous cap for a
# few hundred demo nodes/edges, not a tight squeeze the way Neo4j's heap
# tuning was on the previous version of this file.
echo "Starting Memgraph..."
memgraph --memory-limit=250 &

echo "Waiting for Memgraph to accept connections..."
python3 -c "
import sys
import time

from neo4j import GraphDatabase

for i in range(60):
    try:
        driver = GraphDatabase.driver('bolt://localhost:7687', auth=('${GRAPH_DB_USER}', '${GRAPH_DB_PASSWORD}'))
        driver.verify_connectivity()
        driver.close()
        print('Memgraph is up.')
        break
    except Exception as exc:
        if i == 59:
            print(f'Memgraph never came up after 120s: {exc}', file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
"

echo "Seeding demo data..."
python seed/seed_data.py

echo "Running the pattern engine..."
python pattern_engine/run_pattern_engine.py

# Without --as-of, the flagging agent correctly finds zero flags against
# the full seeded season (see main README's "Flag athletes at risk"
# section) — for a demo, run it against the date where a real historical
# precedent already exists, so a visitor actually has a Flag to click on.
echo "Running the flagging agent (demo --as-of date)..."
python flagging_agent/run_flagging_agent.py --as-of 2025-02-16

echo "Starting the app on port ${PORT}..."
exec uvicorn api.app:app --host 0.0.0.0 --port "${PORT}"
