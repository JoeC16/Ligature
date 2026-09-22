# Deploying to Render

Render's free tier still supports Docker web services with no credit card
required (confirmed current as of writing). This is the recommended free
path — Hugging Face Spaces' Docker SDK now needs a paid PRO plan (see
`deploy/huggingface/README.md`), but the same root `Dockerfile` works on
either, so pick whichever host you'd rather use.

**This uses the root `Dockerfile`** — Memgraph (open-source, no
authentication in the community build) and the app bundled into one
container, since a free instance gets exactly one. An earlier version of
this deploy split Neo4j AuraDB Free (a separate managed instance) out from
the app, after Neo4j's JVM memory footprint turned out not to fit in a
free tier's 512MB — but that path ran into a separate, unresolved Aura
account-side authentication issue across multiple independent networks
and credential resets. Memgraph sidesteps both problems: it's light
enough to bundle back into one container, and its community build has no
password to manage at all, so there's nothing left to mismatch or reset.

## One-time setup

1. Go to [render.com](https://render.com), sign up with **"Continue with
   GitHub"**.
2. **New +** → **Web Service** → connect/select the `JoeC16/Ligature`
   repo, branch **main**.
3. Render should auto-detect the root `Dockerfile` and offer **Docker** as
   the environment. If it instead tries to guess a Python runtime, look
   for an environment/runtime dropdown and switch it to Docker manually.
4. **Instance type: Free.**
5. **Environment variables** — only one is needed:
   - `ANTHROPIC_API_KEY` = your real key (optional — without it,
     everything works except the ask-in-English box, which errors on
     submit)
6. Create the service. First build takes a few minutes.

Your app is live at `https://<service-name>.onrender.com`.

## What to expect

- **750 free instance-hours/month**, pooled across whatever free services
  you run in your Render account.
- **Cold start after inactivity** — free services sleep after ~15 minutes
  idle. Expect something closer to Render's normal ~1 minute wake time
  than the earlier Neo4j-bundled version's 60-90 seconds, since Memgraph
  starts far faster than a JVM database does.
- **Auto-redeploys on every push to `main`** — a Render default.
- **No database password to manage.** Memgraph's community build (what
  the Dockerfile uses) doesn't enforce authentication — the
  `NEO4J_USER`/`NEO4J_PASSWORD` env vars baked into the Dockerfile are
  unused placeholders, kept only because `common/db.py`'s driver call
  always passes an auth tuple. Nothing to reset or rotate for this deploy.
  This is fine because only the app's port (`7860`, mapped via `app_port`
  in the root `README.md`'s frontmatter) is ever exposed to the internet
  — Memgraph's own port never leaves the container.

## Moving to something more robust later

Same as before: the app only ever talks to its graph database through
three env vars (`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`, read in
`common/db.py`) — plus `GRAPH_ENGINE`, which only affects which
constraints file gets applied (`schema/constraints.cypher` for Neo4j,
`schema/constraints.memgraph.cypher` for Memgraph). Moving to a real
Neo4j instance later (for Bloom, GDS, or just because you want Neo4j
specifically) is:

1. Stand up Neo4j wherever you want it to actually live.
2. Point those three env vars at it, and unset `GRAPH_ENGINE` (or set it
   to anything other than `memgraph`) so the Neo4j constraints file is
   used.
3. Re-run `python seed/seed_data.py && python pattern_engine/run_pattern_engine.py`
   against it — or, for real club data, `ingest/ingest_data.py` instead
   (see the main README's "Ingest real (or real-shaped) data" section).

No code changes either way — this repo's `docker-compose.yml` +
`uvicorn --reload` local-dev setup already runs on Neo4j unchanged; the
bundled Memgraph path only exists for this free-tier deploy.
