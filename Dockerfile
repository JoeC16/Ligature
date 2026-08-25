# Bundles Neo4j (community) + the Ligature app in one container, for a
# free public demo on Hugging Face Spaces (Docker SDK) — see
# deploy/huggingface/README.md for the full setup and, more importantly,
# for why bundling here doesn't lock you into it later.
#
# NOT how this project runs in normal local development — that's
# docker-compose.yml (a separate Neo4j container) + `uvicorn api.app:app
# --reload` on the host, per the main README. This Dockerfile exists
# only because a Space gets exactly one container.

FROM neo4j:5-community

# python3-pip alongside python3-venv: Debian's python3-venv doesn't
# reliably bootstrap pip into a new venv (ensurepip) without it present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/venv/bin:${PATH}"

COPY . .
RUN chmod +x deploy/huggingface/entrypoint.sh

# Neo4j's own defaults (see .env.example) — fine for a demo instance with
# no real athlete data. Override NEO4J_PASSWORD as a Space secret if you
# want a non-default one; ANTHROPIC_API_KEY is unset here on purpose, see
# deploy/huggingface/README.md — set it as a Space secret, never bake it
# into the image.
ENV NEO4J_USER=neo4j
ENV NEO4J_PASSWORD=ligature-demo-pw
ENV NEO4J_URI=bolt://localhost:7687
ENV PORT=7860

EXPOSE 7860

ENTRYPOINT ["deploy/huggingface/entrypoint.sh"]
