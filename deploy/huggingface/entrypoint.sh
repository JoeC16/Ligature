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

# Python's stdout is fully block-buffered (not line-buffered) whenever
# it's not attached to a real terminal -- true for every python
# invocation below, since this script's own stdout is just a pipe Render
# captures. Without this, print() output from seed_data.py etc. sits in
# an in-process buffer and only appears in the logs (all at once) when
# the buffer fills or the process exits -- a real multi-minute step looks
# like total silence followed by an instant-looking dump of every line,
# with no way to tell which step actually took the time. This is why a
# production deploy log showed "Connecting to bolt://localhost:7687" and
# "Done." stamped at the exact same second despite ~5 minutes having
# actually passed since "Seeding demo data..." printed.
export PYTHONUNBUFFERED=1

# --memory-limit is in MB. Render's free instance is 512MB total, shared
# with the Python process started below -- Memgraph itself is far lighter
# than Neo4j's JVM (no class metadata, thread-per-connection stacks, or
# off-heap Netty buffers to budget for), so this is a generous cap for a
# few hundred demo nodes/edges, not a tight squeeze the way Neo4j's heap
# tuning was on the previous version of this file.
#
# --bolt-address / --monitoring-address / --metrics-address all pinned to
# 127.0.0.1: Memgraph binds all three to 0.0.0.0 by default (confirmed
# against a real deploy -- Render's own port scan logged "Detected service
# running on port ${PORT} with additional ports HTTP:7444, HTTP:9091,
# TCP:7687"), so all four ports in this container were externally
# reachable and ambiguous to Render's router. 7444 is Memgraph's
# monitoring log channel over WebSocket; a plain page load landing on it
# instead of the app is exactly the shape of the "WebSocket handshake
# Connection field is missing" error seen in production. 9091 is a
# Prometheus metrics endpoint we don't use. 7687 is Bolt itself -- with
# Memgraph's community build having no authentication layer at all, that
# one was a genuinely unauthenticated database reachable from the public
# internet, not just a routing ambiguity. localhost is all this
# entrypoint's own driver connection (below) or the app needs -- nothing
# external should ever talk to Memgraph directly in this bundled deploy.
echo "Starting Memgraph..."
# The binary isn't on PATH in this image -- confirmed from Memgraph's own
# Dockerfile source (memgraph/memgraph's release/docker/v6_deb.dockerfile
# sets ENTRYPOINT ["/usr/lib/memgraph/memgraph"], not a PATH entry). A
# bare `memgraph &` here silently backgrounds a "command not found" no-op,
# which is why the wait loop below timed out on a real deploy.
/usr/lib/memgraph/memgraph \
    --memory-limit=250 \
    --bolt-address=127.0.0.1 \
    --monitoring-address=127.0.0.1 \
    --metrics-address=127.0.0.1 &

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

# Seeding runs in the background, concurrently with the app starting
# below, instead of blocking it -- the 30-player dataset (~25k node/edge
# writes plus a per-athlete flagging pass) is real CPU work, and Render's
# free tier is 0.1 vCPU: roughly 10% of one core. A step that costs, say,
# 60s of actual CPU time costs ~10 minutes of wall clock at that
# throttling -- long enough that Render's own port scan gives up and
# fails the deploy before the app ever gets a chance to start, which is
# exactly what happened blocking on this sequentially. Backing it off
# means Render's port scan succeeds within seconds of Memgraph coming up,
# same as it always did -- a visitor hitting the demo in the first minute
# or two after a cold start may see an empty or still-filling-in graph
# until this finishes, the same "give it a moment" tradeoff as the free
# tier's own cold-start delay banner. set -e doesn't propagate out of a
# backgrounded subshell, so a seeding failure here can't take the app
# down with it -- it'll just show up in the logs and the demo stays
# empty, which is the right degradation for a background job, not a
# silent one: every step still echoes what it's doing.
(
    echo "Seeding demo data..."
    python seed/seed_data.py

    echo "Running the pattern engine..."
    python pattern_engine/run_pattern_engine.py

    # No --as-of needed: seed/generators.py plants a load-spike +
    # wellness-dip echo (same signature as the hamstring cluster) in the
    # final ~12 days of every athlete's own generated data, so the
    # default per-athlete reference date (their own latest data + 1 day)
    # already lands inside it -- a visitor gets real Flags without the
    # demo relying on a hand-picked calendar date.
    echo "Running the flagging agent..."
    python flagging_agent/run_flagging_agent.py

    echo "Demo data ready."
) &

echo "Starting the app on port ${PORT}..."
exec uvicorn api.app:app --host 0.0.0.0 --port "${PORT}"
