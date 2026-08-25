# Deploying to Render

The free alternative to `deploy/huggingface/` — Hugging Face changed policy
in July 2026 so Docker Spaces now need a paid (PRO) plan; Render's free
tier still supports Docker web services with no credit card required
(confirmed July 2026). Same root `Dockerfile` and
`deploy/huggingface/entrypoint.sh` either way (still bundling Neo4j + the
app into one container — a normal Render web service is one container too,
same reasoning as the Spaces doc).

**No token needed for this one** — unlike the Spaces flow, Render deploys
straight from your GitHub repo and auto-redeploys on every push to the
branch you pick, so there's nothing to hand me and nothing for me to push.

## One-time setup

1. Go to [render.com](https://render.com) and sign up — **"Continue with
   GitHub"** is the easiest path on a phone, no separate password to set.
2. **New +** → **Web Service**.
3. Connect your GitHub account if you haven't, then select the
   `JoeC16/Ligature` repo. Grant Render access to it if GitHub asks.
4. Branch: **main** (make sure the deploy PR is merged into `main` first —
   that's what has the `Dockerfile`).
5. Render should auto-detect the root `Dockerfile` and offer **Docker** as
   the environment/runtime. If it instead tries to auto-detect a Python
   runtime, look for an environment/runtime dropdown and switch it to
   Docker manually.
6. Instance type: pick the **Free** tier.
7. Before creating the service, add an environment variable:
   `ANTHROPIC_API_KEY` = your real key (`sk-ant-...`). Without this,
   everything works except the ask-in-English box, which will error on
   submit.
8. Create the service. Render builds the image and deploys — first build
   typically takes a few minutes (it's building Neo4j + Python + the app
   from scratch).

Your app is live at whatever `https://<service-name>.onrender.com` URL
Render assigns (shown on the service's dashboard page).

## What to expect

- **750 free instance-hours/month**, pooled across whatever free services
  you run in your Render account — plenty for a demo that isn't running
  24/7 anyway, since it sleeps when idle (next point).
- **Cold start after inactivity.** Free services sleep after ~15 minutes
  idle. A typical Render app wakes in about a minute; this one is slower,
  because the same container has to boot a full Neo4j instance and
  re-seed the demo graph before the app answers a single request (see
  `deploy/huggingface/README.md`'s "What happens on every container
  start" section — identical behavior here, same entrypoint script).
  Expect more like 60-90 seconds on a cold visit.
- **Auto-redeploys on every push to `main`.** That's a Render default, not
  something set up specially here — worth knowing if you don't want every
  merge to `main` to immediately go live.

Everything else — the demo data being fully synthetic/reproducible, how to
move to a real (non-bundled) Neo4j later, the throwaway demo password —
is identical to the Hugging Face path; see
[`deploy/huggingface/README.md`](../huggingface/README.md) rather than
duplicating it here.
