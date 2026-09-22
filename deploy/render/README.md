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
6. Create the service. First build takes a few minutes — longer than a
   typical Docker service, since the build now also generates the full
   synthetic season and runs the pattern engine + flagging agent against
   it once, baking the result into the image (see "What happens at build
   time vs. every container start" in `deploy/huggingface/README.md` for
   why). That cost is paid once per build, not on every deploy restart.

Your app is live at `https://<service-name>.onrender.com`.

## What to expect

- **750 free instance-hours/month**, pooled across whatever free services
  you run in your Render account.
- **Cold start after inactivity** — free services sleep after ~15 minutes
  idle. Waking back up is fast: the container restores a pre-built
  Memgraph snapshot (baked into the image at build time — see
  `deploy/huggingface/README.md`) rather than regenerating the demo graph
  from scratch, so the graph is already fully populated by the time the
  app answers its first request.
- **Auto-redeploys on every push to `main`** — a Render default.
- **No database password to manage.** Memgraph's community build (what
  the Dockerfile uses, and what `docker-compose.yml` runs for local dev
  too — see the main README) doesn't enforce authentication — the
  `GRAPH_DB_USER`/`GRAPH_DB_PASSWORD` env vars baked into the Dockerfile
  are unused placeholders, kept only because `common/db.py`'s driver call
  always passes an auth tuple. Nothing to reset or rotate, anywhere in
  this project. This is fine because only the app's port (`7860`, mapped
  via `app_port` in the root `README.md`'s frontmatter) is ever exposed
  to the internet — Memgraph's own port never leaves the container.

## Moving to something bigger later

The app only ever talks to its graph database through three env vars
(`GRAPH_DB_URI` / `GRAPH_DB_USER` / `GRAPH_DB_PASSWORD`, read in
`common/db.py`) — it has no idea whether that's this bundled container's
Memgraph or a larger standalone instance elsewhere. Moving to a bigger
Memgraph deployment later (more memory than a free tier's ~512MB, its
own persistent volume instead of this deploy's deliberate
restore-the-baked-snapshot-every-boot ephemeral storage) is:

1. Stand up Memgraph wherever you want it to actually live.
2. Point those three env vars at it.
3. Re-run `python seed/seed_data.py && python pattern_engine/run_pattern_engine.py`
   against it — or, for real club data, `ingest/ingest_data.py` instead
   (see the main README's "Ingest real (or real-shaped) data" section).

No code changes either way.
