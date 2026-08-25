"""Request/response models for the treatment/rehab/outcome input API.

Literal fields render as real dropdowns in FastAPI's auto-generated
Swagger UI (/docs) — that's the "form" half of CLAUDE.md's "simple
internal form or API endpoint" for this step, with no custom UI code.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

TreatmentType = Literal["physio session", "strapping", "massage", "injection", "rest day"]
OutcomeResult = Literal["clean_return", "re_aggravation"]
FlagResolution = Literal["actioned", "dismissed"]


class OpenInjury(BaseModel):
    id: str
    athlete_id: str
    athlete_name: str
    type: str
    body_part: str
    date: str


class Physio(BaseModel):
    id: str
    name: str


class OpenTreatment(BaseModel):
    id: str
    injury_id: str
    date: str
    type: str
    practitioner: str


class OpenRehabSession(BaseModel):
    id: str
    treatment_id: str
    date: str
    protocol: str


class TreatmentCreate(BaseModel):
    injury_id: str
    physio_id: str
    type: TreatmentType
    date: date
    notes: str | None = None


class TreatmentCreated(BaseModel):
    id: str


class RehabSessionCreate(BaseModel):
    treatment_id: str
    date: date
    protocol: str
    load_prescribed: str
    rpe_reported: float = Field(ge=0, le=10, description="Rate of perceived exertion, 0-10")
    completed: bool = True


class RehabSessionCreated(BaseModel):
    id: str
    days_gap: int


class OutcomeCreate(BaseModel):
    rehab_session_id: str
    result: OutcomeResult
    date: date


class OutcomeCreated(BaseModel):
    id: str


class UnreviewedFlag(BaseModel):
    id: str
    athlete_id: str
    athlete_name: str
    date: str
    confidence: float
    shared_metrics: list[str]
    matched_injury_id: str
    matched_injury_type: str
    matched_injury_athlete_name: str


class FlagResolve(BaseModel):
    resolution_state: FlagResolution
    notes: str | None = None


class FlagResolved(BaseModel):
    id: str
    resolution_state: FlagResolution


# --- Frontend graph explorer (build order step 7) ---
# Node/edge shape is uniform across every label (id + label/type + a full
# property map) rather than one model per node type, since the frontend
# treats every node generically until the user clicks it open.


class GraphNode(BaseModel):
    id: str
    label: str
    properties: dict[str, object]


class GraphEdge(BaseModel):
    id: str
    type: str
    from_: str = Field(alias="from")
    to: str
    properties: dict[str, object]


class GraphSubgraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    """Mirrors nl_query/ask.py's ask() result dict. Exactly one of
    summary/refusal_reason/reason/error is populated, matching `status`."""

    status: Literal["ok", "refused", "unsafe", "error"]
    question: str
    summary: str | None = None
    cypher: str | None = None
    rows: list[dict] | None = None
    refusal_reason: str | None = None
    reason: str | None = None
    error: str | None = None
    matched_ids: list[str] = []
