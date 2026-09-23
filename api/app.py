"""Treatment/rehab/outcome input API (build order step 4), flag
resolution write-back (build order step 6), and the graph explorer +
ask-in-english backend for the frontend (build order step 7).

Run:
    uvicorn api.app:app --reload

Then open http://localhost:8000/ for the graph explorer, or
http://localhost:8000/docs for Swagger UI, which renders every Literal
field below as a real dropdown — the "form" half of CLAUDE.md's "simple
internal form or API endpoint, not polished UI yet" for treatment input.

Mirrors the real workflow graph: pick an open injury -> log a Treatment,
pick an open treatment -> log a RehabSession, pick an open rehab session ->
log an Outcome. Each POST validates its referenced ids exist first (404,
not a Cypher MATCH silently matching nothing).

/flags/unreviewed and /flags/{id}/resolve are step 6's other required
build-in-from-the-start piece: a flag raised by flagging_agent/ needs
somewhere a physio can review it and write back reviewed+actioned or
dismissed — reusing this API rather than building a second interface.

/graph/* and /ask back the frontend graph explorer (build order step 7):
a curated starting view, label-dispatched click-to-expand, search, and the
NL query layer's "full integration" CLAUDE.md deferred to "whenever the
frontend arrives."
"""

from __future__ import annotations

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
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(NL_QUERY_DIR))
sys.path.insert(0, str(INGEST_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402

import anthropic  # noqa: E402
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

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
)

# Cheap sanity cap, not a real abuse defense (that needs the auth/rate
# limiting this deploy doesn't have yet) -- just enough to stop a single
# oversized upload from choking a free-tier instance's memory/disk before
# any of that exists.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Ids across this codebase are "{prefix}-{suffix}", e.g. athlete-1,
# injury-athlete1-hamstring, flag-a1b2c3d4. Used by POST /ask to
# best-effort-scan result rows for values worth highlighting on the graph.
ID_PATTERN = re.compile(
    r"^(athlete|session|metric|wellness|injury|treatment|rehab|outcome|note|flag|physio|cluster)-[\w.-]+$"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver = db.connect()
    # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment —
    # this must run after db.connect(), which is what loads .env as a side
    # effect (see common/db.py). Same ordering bug step 5 already hit once.
    app.state.anthropic_client = anthropic.Anthropic()
    yield
    app.state.driver.close()


app = FastAPI(
    title="Ligature",
    description="Graph-native sports biometric intelligence: treatment/rehab input, flag review, and the graph explorer + ask-in-english layer.",
    lifespan=lifespan,
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


@app.get("/injuries/open", response_model=list[OpenInjury])
def list_open_injuries(session=Depends(get_session)):
    return reads.fetch_open_injuries(session)


@app.get("/physios", response_model=list[Physio])
def list_physios(session=Depends(get_session)):
    return reads.fetch_physios(session)


@app.get("/treatments/open", response_model=list[OpenTreatment])
def list_open_treatments(session=Depends(get_session)):
    return reads.fetch_open_treatments(session)


@app.get("/rehab-sessions/open", response_model=list[OpenRehabSession])
def list_open_rehab_sessions(session=Depends(get_session)):
    return reads.fetch_open_rehab_sessions(session)


@app.post("/treatments", response_model=TreatmentCreated, status_code=201)
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


@app.post("/rehab-sessions", response_model=RehabSessionCreated, status_code=201)
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


@app.post("/outcomes", response_model=OutcomeCreated, status_code=201)
def create_outcome(body: OutcomeCreate, session=Depends(get_session)):
    if not reads.rehab_session_exists(session, body.rehab_session_id):
        raise HTTPException(404, f"No rehab session with id '{body.rehab_session_id}'")

    outcome_id = writes.create_outcome(session, body.rehab_session_id, body.result, body.date)
    return OutcomeCreated(id=outcome_id)


@app.get("/flags/unreviewed", response_model=list[UnreviewedFlag])
def list_unreviewed_flags(session=Depends(get_session)):
    return reads.fetch_unreviewed_flags(session)


@app.post("/flags/{flag_id}/resolve", response_model=FlagResolved)
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


@app.post("/ingest", response_model=IngestReport)
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

    No auth on this endpoint yet (tracked separately — a real pilot needs
    per-club data isolation before real athlete data should ever reach
    it); until then this is additive/idempotent against whatever graph is
    already live, same as the CLI."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        roster_path = _save_upload(roster, tmp, "roster.csv")
        gps_path = _save_upload(gps, tmp, "gps.csv") if gps else None
        wellness_path = _save_upload(wellness, tmp, "wellness.csv") if wellness else None
        injuries_path = _save_upload(injuries, tmp, "injuries.csv") if injuries else None
        return run_ingest(session, roster_path, gps_path, wellness_path, injuries_path)


@app.get("/graph/overview", response_model=GraphSubgraph)
def graph_overview(session=Depends(get_session)):
    return graph.fetch_overview(session)


@app.get("/graph/expand/{node_id}", response_model=GraphSubgraph)
def graph_expand(node_id: str, session=Depends(get_session)):
    result = graph.expand_node(session, node_id)
    if result is None:
        raise HTTPException(404, f"No node with id '{node_id}'")
    return result


@app.get("/graph/search", response_model=list[GraphNode])
def graph_search(q: str, session=Depends(get_session)):
    return graph.search_nodes(session, q)


@app.get("/graph/nodes", response_model=list[GraphNode])
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


@app.post("/ask", response_model=AskResponse)
def ask_question(body: AskRequest, session=Depends(get_session), client=Depends(get_anthropic_client)):
    result = run_ask(client, session, body.question)
    matched_ids = _scan_matched_ids(result["rows"]) if result["status"] == "ok" else []
    return AskResponse(**result, matched_ids=matched_ids)


# Mounted last so it never shadows an API route above — StaticFiles(html=True)
# serves frontend/index.html at / and falls through to it for any unknown
# path, which is what makes "uvicorn api.app:app" the one command that runs
# the whole product (API + graph explorer) per this session's step-7 decision.
app.mount("/", StaticFiles(directory=str(REPO_ROOT / "frontend"), html=True), name="frontend")
