# Deploying to Render

The free alternative to `deploy/huggingface/` — Hugging Face changed policy
in July 2026 so Docker Spaces now need a paid (PRO) plan; Render's free
tier still supports web services with no credit card required (confirmed
July 2026).

**This does *not* use the root `Dockerfile`.** That Dockerfile bundles
Neo4j + the app into one container, which was the plan here too — until a
real deploy attempt hit Render's free instance's actual limit (512MB RAM /
0.1 vCPU, confirmed live): Neo4j is a full JVM application, and no amount
of heap/page-cache tuning gets its total footprint under ~512MB. It just
doesn't fit in one free container alongside anything else.

The fix is a split instead: **Neo4j AuraDB Free** (a separate, dedicated,
always-free managed Neo4j instance — not a trial; don't confuse it with
AuraDB *Professional*'s 14-day trial, which is a different plan on the
same signup page) hosts the database with its own resources, and Render
runs *only* the Python app — comfortably light enough for 512MB on its
own. No Docker needed for this path at all; Render's native Python
runtime is simpler than the bundled container was going to be anyway.

**No token needed either** — Render deploys straight from your GitHub
repo and auto-redeploys on every push to the branch you pick.

## One-time setup

### 1. Neo4j AuraDB Free

1. Go to [neo4j.com/product/auradb](https://neo4j.com/product/auradb) (or
   [console.neo4j.io](https://console.neo4j.io)) and create an instance —
   make sure you pick the **Free** plan, not the Professional trial.
2. Note down the **Connection URI** (`neo4j+s://xxxxxxxx.databases.neo4j.io`)
   and the **password** Aura shows you once at creation (username is
   always `neo4j`). If you didn't save the password, reset it from the
   instance's page in the Aura console.

### 2. Render web service

1. Go to [render.com](https://render.com), sign up with **"Continue with
   GitHub"**.
2. **New +** → **Web Service** → connect/select the `JoeC16/Ligature`
   repo, branch **main**.
3. **Environment/Runtime: Python** (not Docker — if you already created a
   Docker-type service from an earlier attempt, either look for a way to
   change its environment in Settings, or just delete it and create a
   fresh one as Python).
4. **Build Command**:
   ```
   pip install -r requirements.txt
   ```
5. **Start Command**:
   ```
   python seed/seed_data.py && python pattern_engine/run_pattern_engine.py && python flagging_agent/run_flagging_agent.py --as-of 2025-02-16 && uvicorn api.app:app --host 0.0.0.0 --port $PORT
   ```
   (Same reasoning as the Hugging Face path's entrypoint script: re-seed
   the fully synthetic, deterministic demo data on every boot rather than
   relying on anything persisting, then run the pattern engine, then the
   flagging agent against a fixed demo date so a real `Flag` exists to
   click on, then serve the app.)
6. **Instance type: Free**.
7. **Environment variables** — add all of these before creating the service:
   - `NEO4J_URI` = your Aura connection URI (`neo4j+s://...`)
   - `NEO4J_USER` = `neo4j`
   - `NEO4J_PASSWORD` = your Aura password
   - `ANTHROPIC_API_KEY` = your real key (optional — without it, everything
     works except the ask-in-English box, which errors on submit)
8. Create the service. Build should be quick now — no Neo4j to compile or
   boot inside this container, and `.python-version` at the repo root
   pins Python to 3.12 so `numpy==1.26.4` installs from a prebuilt wheel
   instead of needing to compile from source (that's what caused the
   earlier build failures on the bundled attempt).

Your app is live at `https://<service-name>.onrender.com`.

## What to expect

- **750 free instance-hours/month**, pooled across whatever free services
  you run in your Render account.
- **Cold start after inactivity** — free services sleep after ~15 minutes
  idle. This one should be close to Render's normal ~1 minute wake time
  now, since the container itself only has to reseed a small dataset and
  start uvicorn, not boot a database too.
- **Auto-redeploys on every push to `main`** — a Render default, not
  something set up specially here.
- Neo4j Aura Free has its own size cap (fine for this repo's few-hundred-
  node synthetic demo dataset; not something you'd hit with real club
  data at any real club's scale either, but worth knowing it's not
  unlimited).

## The bundled Dockerfile still exists — just not for this host's free tier

`Dockerfile` + `deploy/huggingface/entrypoint.sh` at the repo root still
work exactly as documented in `deploy/huggingface/README.md`, for any host
that gives the container more than ~1GB RAM (a paid Render instance type,
a VPS, etc.) — the memory tuning in that entrypoint just isn't enough to
fit Neo4j's JVM overhead into a free tier's 512MB, on any host with that
same ceiling, not just Render's.
