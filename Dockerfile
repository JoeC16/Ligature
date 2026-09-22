# Bundles Memgraph (open-source, no auth in the community build) + the
# Ligature app in one container, for a free public demo on Render or
# Hugging Face Spaces (whichever you use, see deploy/render/README.md and
# deploy/huggingface/README.md) — a free-tier host gets exactly one
# container, so the graph DB and the app share this image.
#
# NOT how this project runs in normal local development — that's
# docker-compose.yml (a separate Neo4j container, since Neo4j's own
# tooling — Bloom, GDS — is worth having for real development) + `uvicorn
# api.app:app --reload` on the host, per the main README. Memgraph is used
# here specifically because it doesn't carry Neo4j's JVM memory overhead,
# which didn't fit in a free tier's ~512MB no matter how it was tuned —
# see the deploy docs for that whole story.
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
RUN chmod +x deploy/huggingface/entrypoint.sh

# Memgraph's community build has no authentication layer at all, so
# NEO4J_USER/PASSWORD below are unused placeholders kept only because
# common/db.py's connect() always passes an auth tuple to the driver —
# there is no password to reset, rotate, or mistype for this deploy path.
# GRAPH_ENGINE=memgraph is what makes common/db.py's run_constraints()
# use schema/constraints.memgraph.cypher instead of the Neo4j one.
ENV GRAPH_ENGINE=memgraph
ENV NEO4J_USER=memgraph
ENV NEO4J_PASSWORD=unused
ENV NEO4J_URI=bolt://localhost:7687
ENV PORT=7860

EXPOSE 7860

ENTRYPOINT ["deploy/huggingface/entrypoint.sh"]
