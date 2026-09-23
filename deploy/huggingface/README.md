# Deploying to Hugging Face Spaces

> **As of a July 2026 policy change, Docker Spaces need a paid PRO plan on
> a personal account** — this path isn't free anymore. See
> [`deploy/render/README.md`](../render/README.md) for the current free
> option (same `Dockerfile`, deploys straight from GitHub, no HF token
> needed). Keeping this doc for anyone who already has PRO or whose plan
> includes it.

A free, public demo URL for Ligature — Memgraph (open-source, no
authentication in the community build) and the app bundled into one
container (`Dockerfile` at the repo root), because a Space gets exactly one.
This is a demo convenience, not how the project runs for local development
day to day — see the main [README](../../README.md) (separate Memgraph
via `docker-compose.yml`, `uvicorn --reload`; that compose file runs
`memgraph-platform`, which bundles Memgraph Lab and MAGE for visual
exploration and graph algorithms, unlike the bare image this Dockerfile
uses for the memory-constrained free-tier deploy).

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

4. **Set two Space secrets** (never commit either): in the Space's
   **Settings → Repository secrets**:
   - `SESSION_SECRET` = a random value, e.g. the output of
     `python -c "import secrets; print(secrets.token_hex(32))"` —
     **required**, the app refuses to start without it (it signs the
     login session cookie; see `api/app.py`). Generate your own — never
     reuse a value from this repo's history or docs.
   - `ANTHROPIC_API_KEY` = `sk-ant-...` (optional — without it, everything
     works *except* the ask-in-English box, which will error on submit —
     the rest of the graph explorer (browsing, search, click-to-expand)
     doesn't need an LLM at all).
   - `ANTHROPIC_WORKSPACE_ID` = only add this if the ask-in-English box
     errors with *"This API key is not scoped to a workspace..."* — an
     org-level key needs this set to the target workspace's id (Anthropic
     Console → that workspace) on every request. A workspace-scoped key
     needs no header and no action here.

That's it — the Space builds, and in a few minutes you have a public URL at
`https://huggingface.co/spaces/<your-username>/<space-name>`.

## Logging in

Every page now requires a login (see `api/app.py`'s `require_auth`). The
build bakes in one demo account, credentials intentionally public since
this account reaches nothing but the synthetic season below — no real
data for a public password to expose:

- **Email:** `demo@ligature.app`
- **Password:** `ligature-demo`

To add a real staff account instead (for a real pilot deploy, not this
public demo), see the main README's auth section and `auth/create_user.py`.

## What happens at build time vs. every container start

The full synthetic-season pipeline (`seed/seed_data.py` →
`pattern_engine/run_pattern_engine.py` → `flagging_agent/run_flagging_agent.py`,
no `--as-of` override needed — the seed data plants its flagging-echo
cohort at the end of the generated season, so the agent's default
per-athlete reference date already produces real `Flag`s to click on)
runs **once, at `docker build` time** (`deploy/huggingface/build_seed.sh`),
against a throwaway Memgraph instance, and the result is written to a
Memgraph snapshot baked into the image. That used to run on every
container *boot* instead — real CPU work (~25k node/edge writes plus a
per-athlete flagging pass) that a free instance's 0.1 vCPU either
couldn't finish before the host's own health check gave up and failed the
deploy outright, or (once backgrounded to dodge that) left a visitor
looking at an empty, still-filling-in graph for the first minute or two
of every cold start. Moving it to build time means the CPU-heavy part
isn't racing a health-check timeout anymore — a slower `docker build` is
a fine trade for a deploy that comes up complete.

`deploy/huggingface/entrypoint.sh` now just restores that baked snapshot
into Memgraph's real data directory, starts Memgraph (which recovers it
in seconds, not the minutes the original synthesis took), waits for it to
accept connections, and only then starts the app — so the graph is
already fully populated by the time it answers its first request. This
is deliberate, not a workaround: a free Space's disk is ephemeral, and
the baked snapshot is fully synthetic and deterministic
(`generators.SEED`), so restoring it on every boot just means every
visitor sees the same known-good demo graph regardless of when the
container last restarted. **Don't use this Space to log real data** —
anything written through the API (a real treatment, a resolved flag) is
gone on the next restart, and free Spaces do restart on their own
(inactivity sleep, periodic maintenance).

## What to expect

- **Build is slower than a typical Space** — `docker build` now includes
  generating the full synthetic season and running the pattern engine
  and flagging agent against it once, before the image is even pushed.
  **Cold start itself is fast**: Free-tier Spaces sleep after ~15-30
  minutes of no traffic, and waking back up only costs restoring a
  pre-built snapshot and booting Memgraph (seconds, not the minutes the
  original from-scratch re-seed took) before the app answers a request.
  Once warm, it behaves like any local run.
- **No database password to manage.** Memgraph's community build doesn't
  enforce authentication at all — the `GRAPH_DB_USER`/`GRAPH_DB_PASSWORD`
  env vars in the `Dockerfile` are unused placeholders, kept only because
  `common/db.py`'s driver call always passes an auth tuple. This is safe
  because only the app's port (7860, what `app_port: 7860` in the root
  `README.md`'s frontmatter tells Spaces to proxy) is ever exposed —
  Memgraph's own port never leaves the container. Nothing sensitive in
  the seed data either way — it's synthetic.

## Moving to something bigger later

Nothing here locks you in. The app only ever talks to its graph database
through three env vars (`GRAPH_DB_URI` / `GRAPH_DB_USER` /
`GRAPH_DB_PASSWORD`, read in `common/db.py`) — it has no idea whether
that's this bundled container's Memgraph or a larger standalone instance
a thousand miles away. To move to a bigger Memgraph deployment later
(more memory than a free tier's ~512MB, its own persistent volume
instead of this deploy's deliberate restore-the-baked-snapshot-every-boot
ephemeral storage):

1. Stand up Memgraph wherever you want it to actually live.
2. Point those three env vars at it (as Space secrets, or in whatever
   platform you move the app to).
3. Re-run `python seed/seed_data.py && python pattern_engine/run_pattern_engine.py`
   against it — or, once you have real club data, use
   `ingest/ingest_data.py` instead of the synthetic seed (see the main
   README's "Ingest real (or real-shaped) data" section).

No code changes either way — this is a config swap, not a migration,
specifically because the demo data is synthetic and reproducible rather
than something real that would need exporting.
