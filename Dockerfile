# Bundles Memgraph (open-source, no auth in the community build) + the
# Ligature app in one container, for a free public demo on Render or
# Hugging Face Spaces (whichever you use, see deploy/render/README.md and
# deploy/huggingface/README.md) — a free-tier host gets exactly one
# container, so the graph DB and the app share this image.
#
# NOT how this project runs in normal local development — that's
# docker-compose.yml (a separate Memgraph container, with Lab + MAGE
# bundled for visual exploration and graph algorithms) + `uvicorn
# api.app:app --reload` on the host, per the main README. This Dockerfile
# uses the bare memgraph/memgraph image instead (no Lab/MAGE) since this
# deploy is memory-constrained and headless — a free tier's ~512MB is
# already the whole reason this project moved off Neo4j's JVM, which
# didn't fit no matter how it was tuned; see the deploy docs for that
# whole story.
#
# NOT build-tested end to end in this sandbox (no Docker daemon
# available here) — reviewed carefully, but the first real build on your
# host is the actual test, same as every prior Dockerfile change in this
# repo's history.

FROM memgraph/memgraph:latest

# The base image runs as a non-root `memgraph` user by default; apt-get
# needs root.
USER root

# python3-pip alongside python3-venv: Debian's python3-venv doesn't
# reliably bootstrap pip into a new venv (ensurepip) without it present.
# build-essential + python3-dev: in case this base image's Python doesn't
# have a prebuilt wheel for every requirements.txt pin (numpy in
# particular hit exactly this on the previous Neo4j-based image) — having
# a compiler and Python's C headers present means pip can build from
# source instead of failing outright, regardless of which Python version
# this image ships.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip python3-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/venv/bin:${PATH}"

COPY . .
RUN chmod +x deploy/huggingface/entrypoint.sh deploy/huggingface/build_seed.sh

# Memgraph's community build has no authentication layer at all, so
# GRAPH_DB_USER/PASSWORD below are unused placeholders kept only because
# common/db.py's connect() always passes an auth tuple to the driver —
# there is no password to reset, rotate, or mistype for this deploy path.
ENV GRAPH_DB_USER=memgraph
ENV GRAPH_DB_PASSWORD=unused
ENV GRAPH_DB_URI=bolt://localhost:7687
ENV PORT=7860

# /app/seed-snapshot (deliberately NOT under /var/lib/memgraph, the path
# the base image declares as a VOLUME — see the USER note below) holds
# the demo graph build_seed.sh bakes in below. Created + chowned here,
# as root, because the COPY above left /app itself root-owned; the
# `memgraph` user that build_seed.sh actually runs as needs write access
# to create a data directory inside it.
RUN mkdir -p /app/seed-snapshot && chown memgraph:memgraph /app/seed-snapshot

# Drop back to the base image's non-root `memgraph` user for everything that
# actually runs (build_seed.sh below, the entrypoint, memgraph itself,
# uvicorn). The base image's own Dockerfiles follow this exact pattern --
# root only for privileged build steps (apt-get above), switched back
# before anything runs -- because the VOLUME this image declares at
# /var/lib/memgraph is pre-owned by `memgraph`, and the memgraph binary
# refuses to start under any other UID:
#   "The process is running as user root, but '/var/lib/memgraph' is owned
#   by user memgraph. Please start the process as user memgraph!"
# Nothing running after this line writes anywhere outside /app/seed-snapshot
# (see build_seed.sh) and that volume -- /app and /venv only need to be
# read + executed, which COPY's and the venv build's default
# (world-readable/executable) permissions already allow.
USER memgraph

# Generates the full synthetic season, runs the pattern engine and
# flagging agent against it, and snapshots the result to
# /app/seed-snapshot -- once, now, as part of the image -- instead of
# leaving that CPU-heavy pipeline to run on every container boot. See
# build_seed.sh for the full rationale and entrypoint.sh for how the
# baked snapshot gets restored at runtime.
RUN deploy/huggingface/build_seed.sh

EXPOSE 7860

ENTRYPOINT ["deploy/huggingface/entrypoint.sh"]
