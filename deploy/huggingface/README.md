# Deploying to Hugging Face Spaces

A free, public demo URL for Ligature — Neo4j and the app bundled into one
container (`Dockerfile` at the repo root), because a Space gets exactly one.
This is a demo convenience, not how the project is meant to run day to day —
see the main [README](../../README.md) for normal local development
(separate Neo4j via `docker-compose.yml`, `uvicorn --reload`).

## One-time setup

1. Create a free account at [huggingface.co](https://huggingface.co) if you
   don't have one.
2. Create a new Space: **huggingface.co/new-space** →
   - Space SDK: **Docker**
   - Visibility: **Public** (or Private if you'd rather share the link
     selectively — either works, this doesn't change anything below)
   - Anything else (name, license) is up to you.
3. Hugging Face gives you a git remote URL for the new Space, something
   like `https://huggingface.co/spaces/<your-username>/<space-name>`. From
   this repo:

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
   git push space main
   ```

   (You'll be prompted for Hugging Face credentials — an access token from
   your HF settings works as the password.) Spaces builds the `Dockerfile`
   at the repo root automatically on every push to this remote.

4. **Set your Anthropic key as a Space secret** (never commit it): in the
   Space's **Settings → Repository secrets**, add
   `ANTHROPIC_API_KEY` = `sk-ant-...`. Without this, everything works
   *except* the ask-in-English box, which will error on submit — the rest
   of the graph explorer (browsing, search, click-to-expand) doesn't need
   an LLM at all.

That's it — the Space builds, and in a few minutes you have a public URL at
`https://huggingface.co/spaces/<your-username>/<space-name>`.

## What happens on every container start

`deploy/huggingface/entrypoint.sh` starts Neo4j, waits for it to accept
connections, then re-seeds the demo graph from scratch
(`seed/seed_data.py` → `pattern_engine/run_pattern_engine.py` →
`flagging_agent/run_flagging_agent.py --as-of 2025-02-16`, the same demo
date the main README uses to make sure a real `Flag` exists to click on)
before starting the app. This is deliberate, not a workaround: a free
Space's disk is ephemeral, and this repo's seed data is fully synthetic
and deterministic (`generators.SEED`), so re-seeding on boot just means
every visitor sees the same known-good demo graph regardless of when the
container last restarted. **Don't use this Space to log real data** —
anything written through the API (a real treatment, a resolved flag) is
gone on the next restart, and free Spaces do restart on their own
(inactivity sleep, periodic maintenance).

## What to expect

- **Cold start is slower than a typical Space.** Free-tier Spaces sleep
  after ~15-30 minutes of no traffic, and this one has to boot Neo4j and
  re-seed before the app answers a single request — expect 60-90 seconds
  on the first visit after a sleep, not the few seconds a plain web app
  would take. Once warm, it behaves like any local run.
- The demo Neo4j password (`ligature-demo-pw`, set in the `Dockerfile`) is
  not a real secret — Neo4j's ports (7474/7687) aren't exposed outside the
  container, only the app's port 7860 is reachable at all (that's what
  `app_port: 7860` in the root `README.md`'s frontmatter tells Spaces to
  proxy). There's nothing sensitive in the seed data either way — it's
  synthetic.

## Moving to something more robust later

Nothing here locks you in. The app only ever talks to Neo4j through three
env vars (`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`, read in
`common/db.py`) — it has no idea whether Neo4j is bundled in the same
container or a thousand miles away. To move to a real setup (e.g. a
dedicated Neo4j AuraDB instance + the app on its own host):

1. Stand up Neo4j wherever you want it to actually live.
2. Point those three env vars at it (as Space secrets, or in whatever
   platform you move the app to).
3. Re-run `python seed/seed_data.py && python pattern_engine/run_pattern_engine.py`
   against it — or, once you have real club data, use
   `ingest/ingest_data.py` instead of the synthetic seed (see the main
   README's "Ingest real (or real-shaped) data" section).

No code changes either way — this is a config swap, not a migration,
specifically because the demo data is synthetic and reproducible rather
than something real that would need exporting.
