#!/bin/bash
# Container entrypoint for the Hugging Face Space build (see ../../Dockerfile).
# Starts Neo4j as a background daemon, waits for it to accept connections,
# (re)seeds the demo data — safe and idempotent, since seed_data.py always
# wipes+reloads deterministically and the pattern engine's own edges are a
# scoped delete+recompute — then serves the app in the foreground.
#
# Re-seeding on every container start isn't a workaround, it's the right
# behavior here: a free Space's storage is ephemeral (a restart can wipe
# /data), and this repo's seed data is fully synthetic and reproducible,
# so "re-seed on boot" just means every visitor sees the same known-good
# demo graph regardless of when the container last restarted.

set -euo pipefail

# Overriding the base neo4j image's own ENTRYPOINT (this script) means its
# built-in NEO4J_AUTH handling never runs — that's normally what calls
# `neo4j-admin dbms set-initial-password` on first boot. Do it ourselves,
# before starting the server. This only succeeds on a fresh, uninitialized
# /data (true on every boot here, since this Dockerfile mounts no
# persistent volume — see the main entrypoint comment above); if it's ever
# run against an already-initialized database the command fails harmlessly
# and the existing password stands, so this is safe either way.
echo "Setting initial Neo4j password..."
neo4j-admin dbms set-initial-password "${NEO4J_PASSWORD}" \
  || echo "Initial password already set (non-fresh /data) — continuing with the existing one."

echo "Starting Neo4j..."
neo4j start

echo "Waiting for Neo4j to accept connections..."
for i in $(seq 1 60); do
  if cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "RETURN 1" >/dev/null 2>&1; then
    echo "Neo4j is up."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "Neo4j never came up after 120s — aborting." >&2
    exit 1
  fi
  sleep 2
done

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
