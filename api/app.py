"""Treatment/rehab/outcome input API (build order step 4), plus flag
resolution write-back (build order step 6).

Run:
    uvicorn api.app:app --reload

Then open http://localhost:8000/docs — Swagger UI renders every Literal
field below as a real dropdown, which is the "form" half of CLAUDE.md's
"simple internal form or API endpoint, not polished UI yet."

Mirrors the real workflow graph: pick an open injury -> log a Treatment,
pick an open treatment -> log a RehabSession, pick an open rehab session ->
log an Outcome. Each POST validates its referenced ids exist first (404,
not a Cypher MATCH silently matching nothing).

/flags/unreviewed and /flags/{id}/resolve are step 6's other required
build-in-from-the-start piece: a flag raised by flagging_agent/ needs
somewhere a physio can review it and write back reviewed+actioned or
dismissed — reusing this API rather than building a second interface.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import date as date_cls
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
REPO_ROOT = API_DIR.parent
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402

import reads  # noqa: E402
import writes  # noqa: E402
from schemas import (  # noqa: E402
    FlagResolve,
    FlagResolved,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver = db.connect()
    yield
    app.state.driver.close()


app = FastAPI(
    title="Ligature — Treatment/Rehab Input",
    description="Structured quick-entry for physios. Not the polished frontend (build order step 7) — this is the wedge that closes the treatment-outcome loop.",
    lifespan=lifespan,
)


def get_session(request: Request):
    session = request.app.state.driver.session()
    try:
        yield session
    finally:
        session.close()


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
