#!/bin/bash
# Container entrypoint for the bundled free-tier deploy (see ../../Dockerfile
# -- shared by both deploy/render/README.md and deploy/huggingface/README.md).
# Restores the demo graph baked at build time (see build_seed.sh) into
# Memgraph's real data directory, starts Memgraph, waits for it to accept
# connections, then serves the app in the foreground.
#
# This used to run the full seed/pattern-engine/flagging-agent pipeline on
# every container boot -- first blocking on it (which delayed the app past
# Render's own port-scan health check and failed the deploy outright on
# the 30-player dataset), then backgrounding it (which kept the app inside
# the health-check window, but left visitors looking at an empty,
# still-filling-in graph for the first minute or two of every cold start).
# Both were symptoms of the same problem: that pipeline is real CPU work
# (~25k node/edge writes plus a per-athlete flagging pass), and Render's
# free tier is 0.1 vCPU -- roughly 10% of one core. Moving it to build_seed.sh
# means it runs exactly once, at `docker build` time, against a build host
# that isn't racing a health-check timeout -- what's left here is a file
# copy and a snapshot load, which is seconds, not minutes, even at 0.1
# vCPU. The graph is fully populated before uvicorn ever accepts a
# request, and it's fast enough to actually get there.
#
# Restoring on every container start isn't a workaround, it's the right
# behavior here: a free host's storage is ephemeral (a restart can wipe
# /data), and the baked snapshot is fully synthetic and reproducible, so
# "restore on boot" just means every visitor sees the same known-good demo
# graph regardless of when the container last restarted.

set -euo pipefail

# Python's stdout is fully block-buffered (not line-buffered) whenever
# it's not attached to a real terminal -- true for every python
# invocation below, since this script's own stdout is just a pipe Render
# captures. Without this, print() output sits in an in-process buffer and
# only appears in the logs (all at once) when the buffer fills or the
# process exits.
export PYTHONUNBUFFERED=1

# Always start from a clean data directory before restoring: a free
# host's ephemeral storage means this is usually already empty on a cold
# start, but relying on that would mean a host that *does* persist
# storage across restarts could boot with a stale prior version's data
# still in place, silently never picking up a newer baked snapshot.
# `find -delete` rather than `rm -rf .../*`: this is /var/lib/memgraph
# itself (a VOLUME mount point per the base image), so the directory
# entry has to survive -- only what's inside it should go, dotfiles
# included, which a bare `*` glob wouldn't catch anyway.
echo "Restoring the baked demo snapshot..."
find /var/lib/memgraph -mindepth 1 -delete
cp -a /app/seed-snapshot/. /var/lib/memgraph/

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
python3 deploy/huggingface/wait_for_bolt.py

echo "Starting the app on port ${PORT}..."
exec uvicorn api.app:app --host 0.0.0.0 --port "${PORT}"
