"""Treatment/rehab/outcome input API (build order step 4), flag
resolution write-back (build order step 6), the graph explorer +
ask-in-english backend for the frontend (build order step 7), CSV
ingestion (build order step 2's browser upload path), and login (every
/api/* route below requires a session — see require_auth and
SESSION_SECRET).

Run:
    uvicorn api.app:app --reload

Then open http://localhost:8000/ (redirects to /login.html if you don't
have a session yet — see auth/create_user.py for creating one) for the
graph explorer, or http://localhost:8000/docs for Swagger UI, which
renders every Literal field below as a real dropdown — the "form" half of
CLAUDE.md's "simple internal form or API endpoint, not polished UI yet"
for treatment input. Swagger's own "Try it out" still needs a real
browser session cookie to get past require_auth, same as any other client.

Every data route lives under /api/ — not for REST style, but so
require_auth can enforce "every /api/* path needs a session, no
exceptions" as one prefix check instead of an opt-in per route. /health
and the static frontend files (served from "/") are the only things
that sit outside it, deliberately public.

Mirrors the real workflow graph: pick an open injury -> log a Treatment,
pick an open treatment -> log a RehabSession, pick an open rehab session ->
log an Outcome. Each POST validates its referenced ids exist first (404,
not a Cypher MATCH silently matching nothing).

/api/flags/unreviewed and /api/flags/{id}/resolve are step 6's other
required build-in-from-the-start piece: a flag raised by flagging_agent/
needs somewhere a physio can review it and write back reviewed+actioned
or dismissed — reusing this API rather than building a second interface.

/api/graph/* and /api/ask back the frontend graph explorer (build order
step 7): a curated starting view, label-dispatched click-to-expand,
search, and the NL query layer's "full integration" CLAUDE.md deferred to
"whenever the frontend arrives."
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import date as date_cls
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
REPO_ROOT = API_DIR.parent
NL_QUERY_DIR = REPO_ROOT / "nl_query"
INGEST_DIR = REPO_ROOT / "ingest"
AUTH_DIR = REPO_ROOT / "auth"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(NL_QUERY_DIR))
sys.path.insert(0, str(INGEST_DIR))
sys.path.insert(0, str(AUTH_DIR))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

# Loaded explicitly here, not left to common/db.py's connect() side effect:
# SessionMiddleware needs SESSION_SECRET at import time (app.add_middleware
# below), which runs before lifespan() ever calls db.connect() -- the same
# ordering bug this file already hit once with the Anthropic client (see
# lifespan()'s own comment). .env has to be loaded before anything reads
# os.environ, not after.
load_dotenv(REPO_ROOT / ".env")

from common import db  # noqa: E402

import anthropic  # noqa: E402
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

import graph  # noqa: E402
import reads  # noqa: E402
import writes  # noqa: E402
from ask import ask as run_ask  # noqa: E402
from ingest_data import run_ingest  # noqa: E402
from schemas import (  # noqa: E402
    AskRequest,
    AskResponse,
    FlagResolve,
    FlagResolved,
    GraphNode,
    GraphSubgraph,
    IngestReport,
    LoginRequest,
    OpenInjury,
    OpenRehabSession,
    OpenTreatment,
    OutcomeCreate,
    OutcomeCreated,
    Physio,
    RehabSessionCreate,
    RehabSessionCreated,
    TreatmentCreate,
    TreatmentCreated,
    UnreviewedFlag,
    UserProfile,
)
from users import get_user_by_id, verify_password  # noqa: E402

# Cheap sanity cap, not a real abuse defense (rate limiting is a separate,
# not-yet-built concern) -- just enough to stop a single oversized upload
# from choking a free-tier instance's memory/disk.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Ids across this codebase are "{prefix}-{suffix}", e.g. athlete-1,
# injury-athlete1-hamstring, flag-a1b2c3d4. Used by POST /api/ask to
# best-effort-scan result rows for values worth highlighting on the graph.
ID_PATTERN = re.compile(
    r"^(athlete|session|metric|wellness|injury|treatment|rehab|outcome|note|flag|physio|cluster)-[\w.-]+$"
)

# Required, no fallback: a guessable/default session-signing secret baked
# into source would let anyone forge a valid login cookie, defeating the
# entire point of adding auth. Every deploy (including local dev) sets its
# own -- see .env.example for how to generate one. Failing loudly at
# startup here is deliberate: better an obvious crash than a real pilot
# deploy silently running on a secret an attacker could guess or find in
# this repo's own history.
SESSION_SECRET = os.environ["SESSION_SECRET"]

# Cookies are Secure (HTTPS-only) by default -- every real deploy target
# (Render, HF Spaces) terminates TLS in front of the app. Local dev over
# plain http needs COOKIE_SECURE=false in .env, or the browser silently
# drops the cookie and login appears to "not work."
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver = db.connect()
    # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment —
    # this must run after db.connect(), which is what loads .env as a side
    # effect (see common/db.py). Same ordering bug step 5 already hit once.
    #
    # ANTHROPIC_WORKSPACE_ID is optional and usually unnecessary — only
    # needed for an org-level API key that isn't scoped to one workspace,
    # which the API otherwise rejects with "This API key is not scoped to
    # a workspace..." (seen on the live deploy). A workspace-scoped key
    # needs no header at all; this exists for whichever kind of key you'd
    # rather keep using.
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    default_headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
    app.state.anthropic_client = anthropic.Anthropic(default_headers=default_headers)
    yield
    app.state.driver.close()


app = FastAPI(
    title="Ligature",
    description="Graph-native sports biometric intelligence: treatment/rehab input, flag review, and the graph explorer + ask-in-english layer.",
    lifespan=lifespan,
)

# Every /api/* route requires a session except login itself -- enforced
# once, here, rather than as a Depends() on each route below. A per-route
# opt-in (remembering to add Depends(require_user) to every new endpoint)
# is exactly the kind of thing one missed line quietly leaves unprotected;
# this fails closed instead: a new /api/* route is auth-gated automatically
# the moment it exists, with no separate step to remember. Static frontend
# files (served from "/" below) and /health intentionally sit outside
# /api/* and are never gated here -- the frontend shell itself is public,
# only the data it calls is not.
#
# Registered BEFORE SessionMiddleware below on purpose -- Starlette wraps
# middleware in reverse registration order (the *last* one added becomes
# the *outermost* layer, so it's the first to touch an incoming request).
# request.session only exists once SessionMiddleware has run, so it has to
# end up outside this one; getting that backwards doesn't fail at import
# time, it fails on the first real request with "SessionMiddleware must be
# installed to access request.session" -- confirmed the hard way against a
# TestClient before landing on this ordering.
PUBLIC_API_PATHS = {"/api/auth/login"}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        if not request.session.get("user_id"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


# SameSite=Lax blocks the cookie on cross-site POST/fetch (the CSRF vector
# that matters for a session cookie protecting write endpoints) while still
# sending it on ordinary top-level navigation (a shared/bookmarked link).
# max_age is 14 days -- long enough that a physio checking in once a day
# during a pilot doesn't get logged out mid-week, short enough that a
# stolen cookie doesn't stay valid indefinitely.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=COOKIE_SECURE,
    max_age=14 * 24 * 60 * 60,
)


def get_session(request: Request):
    session = request.app.state.driver.session()
    try:
        yield session
    finally:
        session.close()


def get_anthropic_client(request: Request):
    return request.app.state.anthropic_client


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=UserProfile)
def login(body: LoginRequest, request: Request, session=Depends(get_session)):
    user = verify_password(session, body.email, body.password)
    if user is None:
        raise HTTPException(401, "Incorrect email or password")
    request.session["user_id"] = user["id"]
    return user


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.get("/api/auth/me", response_model=UserProfile)
def whoami(request: Request, session=Depends(get_session)):
    # require_auth already guarantees session["user_id"] is set to reach
    # this line -- the None-check below isn't dead code, though: it's
    # reachable if the account behind an otherwise-valid session cookie
    # was deleted after the cookie was issued.
    user = get_user_by_id(session, request.session["user_id"])
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


@app.get("/api/injuries/open", response_model=list[OpenInjury])
def list_open_injuries(session=Depends(get_session)):
    return reads.fetch_open_injuries(session)


@app.get("/api/physios", response_model=list[Physio])
def list_physios(session=Depends(get_session)):
    return reads.fetch_physios(session)


@app.get("/api/treatments/open", response_model=list[OpenTreatment])
def list_open_treatments(session=Depends(get_session)):
    return reads.fetch_open_treatments(session)


@app.get("/api/rehab-sessions/open", response_model=list[OpenRehabSession])
def list_open_rehab_sessions(session=Depends(get_session)):
    return reads.fetch_open_rehab_sessions(session)


@app.post("/api/treatments", response_model=TreatmentCreated, status_code=201)
def create_treatment(body: TreatmentCreate, session=Depends(get_session)):
    if not reads.injury_exists(session, body.injury_id):
        raise HTTPException(404, f"No injury with id '{body.injury_id}'")
    physio = reads.fetch_physio(session, body.physio_id)
    if physio is None:
        raise HTTPException(404, f"No physio with id '{body.physio_id}'")

    treatment_id = writes.create_treatment(
        session, body.injury_id, body.physio_id, physio["name"], body.type, body.date, body.notes
    )
    return TreatmentCreated(id=treatment_id)


@app.post("/api/rehab-sessions", response_model=RehabSessionCreated, status_code=201)
def create_rehab_session(body: RehabSessionCreate, session=Depends(get_session)):
    treatment_date_str = reads.fetch_treatment_date(session, body.treatment_id)
    if treatment_date_str is None:
        raise HTTPException(404, f"No treatment with id '{body.treatment_id}'")

    treatment_date = date_cls.fromisoformat(treatment_date_str)
    if body.date < treatment_date:
        raise HTTPException(422, "Rehab session date can't be before the treatment date")

    rehab_id, days_gap = writes.create_rehab_session(
        session,
        body.treatment_id,
        treatment_date,
        body.date,
        body.protocol,
        body.load_prescribed,
        body.rpe_reported,
        body.completed,
    )
    return RehabSessionCreated(id=rehab_id, days_gap=days_gap)


@app.post("/api/outcomes", response_model=OutcomeCreated, status_code=201)
def create_outcome(body: OutcomeCreate, session=Depends(get_session)):
    if not reads.rehab_session_exists(session, body.rehab_session_id):
        raise HTTPException(404, f"No rehab session with id '{body.rehab_session_id}'")

    outcome_id = writes.create_outcome(session, body.rehab_session_id, body.result, body.date)
    return OutcomeCreated(id=outcome_id)


@app.get("/api/flags/unreviewed", response_model=list[UnreviewedFlag])
def list_unreviewed_flags(session=Depends(get_session)):
    return reads.fetch_unreviewed_flags(session)


@app.post("/api/flags/{flag_id}/resolve", response_model=FlagResolved)
def resolve_flag(flag_id: str, body: FlagResolve, session=Depends(get_session)):
    if not reads.flag_exists(session, flag_id):
        raise HTTPException(404, f"No flag with id '{flag_id}'")

    writes.resolve_flag(session, flag_id, body.resolution_state, body.notes)
    return FlagResolved(id=flag_id, resolution_state=body.resolution_state)


def _save_upload(upload: UploadFile, dest_dir: Path, filename: str) -> str:
    content = upload.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{upload.filename or filename} is over the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit")
    dest = dest_dir / filename
    dest.write_bytes(content)
    return str(dest)


@app.post("/api/ingest", response_model=IngestReport)
def ingest_files(
    roster: UploadFile = File(..., description="Athlete roster CSV — required, every other file resolves athletes against it"),
    gps: UploadFile | None = File(None, description="GPS/session export CSV"),
    wellness: UploadFile | None = File(None, description="Wellness survey export CSV"),
    injuries: UploadFile | None = File(None, description="Injury log CSV"),
    session=Depends(get_session),
):
    """Upload half of ingest/ingest_data.py's CLI pipeline (build order
    step 2's "full integration" — this codebase's other CLI-only pipeline,
    same treatment step 5/7 already gave the NL query layer and the
    treatment/rehab input API). Saves each upload to a throwaway temp
    directory, runs the exact same run_ingest() the CLI calls, and returns
    its report — the CLI and this route can never drift apart on what
    counts as a successfully-loaded row versus a skip.

    Requires a session, like every other /api/* route (see require_auth
    above) — this is additive/idempotent against whatever graph is
    already live, same as the CLI, but it's still a write endpoint that
    now needs a logged-in user, not the public internet."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        roster_path = _save_upload(roster, tmp, "roster.csv")
        gps_path = _save_upload(gps, tmp, "gps.csv") if gps else None
        wellness_path = _save_upload(wellness, tmp, "wellness.csv") if wellness else None
        injuries_path = _save_upload(injuries, tmp, "injuries.csv") if injuries else None
        return run_ingest(session, roster_path, gps_path, wellness_path, injuries_path)


@app.get("/api/graph/overview", response_model=GraphSubgraph)
def graph_overview(session=Depends(get_session)):
    return graph.fetch_overview(session)


@app.get("/api/graph/expand/{node_id}", response_model=GraphSubgraph)
def graph_expand(node_id: str, session=Depends(get_session)):
    result = graph.expand_node(session, node_id)
    if result is None:
        raise HTTPException(404, f"No node with id '{node_id}'")
    return result


@app.get("/api/graph/search", response_model=list[GraphNode])
def graph_search(q: str, session=Depends(get_session)):
    return graph.search_nodes(session, q)


@app.get("/api/graph/nodes", response_model=list[GraphNode])
def graph_nodes(ids: str, session=Depends(get_session)):
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return graph.fetch_nodes_by_ids(session, id_list)


def _scan_matched_ids(rows: list[dict]) -> list[str]:
    """Best-effort: walk every value in the result rows and collect
    anything shaped like this codebase's ids, so the frontend can
    fetch+highlight whichever aren't already on screen. Not a general
    result-to-graph mapper — just enough for the common case of an answer
    whose rows are (or contain) real node ids."""
    seen: dict[str, None] = {}

    def walk(value):
        if isinstance(value, str):
            if ID_PATTERN.match(value):
                seen[value] = None
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(rows)
    return list(seen)


@app.post("/api/ask", response_model=AskResponse)
def ask_question(body: AskRequest, session=Depends(get_session), client=Depends(get_anthropic_client)):
    result = run_ask(client, session, body.question)
    matched_ids = _scan_matched_ids(result["rows"]) if result["status"] == "ok" else []
    return AskResponse(**result, matched_ids=matched_ids)


# Mounted last so it never shadows an API route above — StaticFiles(html=True)
# serves frontend/index.html at / and falls through to it for any unknown
# path, which is what makes "uvicorn api.app:app" the one command that runs
# the whole product (API + graph explorer) per this session's step-7 decision.
app.mount("/", StaticFiles(directory=str(REPO_ROOT / "frontend"), html=True), name="frontend")
