from contextlib import asynccontextmanager
from datetime import datetime
import json

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, Session, SQLModel, select
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from .agent.events import run_event_hub
from .db import create_db_and_tables, get_session
from .models import EvidenceArtifact, Incident, InvestigationRun


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Autopsy Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SessionDep = Annotated[Session, Depends(get_session)]


class IncidentCreate(SQLModel):
    title: str
    started_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: str = "open"


class InvestigationRunCreate(SQLModel):
    status: str = "running"


class ArtifactCreate(SQLModel):
    tool_name: str
    input_json: dict[str, object] = Field(default_factory=dict)
    output_json: dict[str, object] = Field(default_factory=dict)
    summary: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/incidents", response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, session: SessionDep) -> Incident:
    incident = Incident(**payload.model_dump(exclude_none=True))
    session.add(incident)
    session.commit()
    session.refresh(incident)
    return incident


@app.get("/incidents", response_model=list[Incident])
def list_incidents(session: SessionDep) -> list[Incident]:
    return list(session.exec(select(Incident).order_by(Incident.started_at.desc())).all())


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: int, session: SessionDep) -> dict[str, object]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    runs = list(session.exec(select(InvestigationRun).where(InvestigationRun.incident_id == incident_id)).all())
    return {"incident": incident, "runs": runs}


@app.post("/incidents/{incident_id}/runs", response_model=InvestigationRun, status_code=status.HTTP_201_CREATED)
def create_run(incident_id: int, payload: InvestigationRunCreate, session: SessionDep) -> InvestigationRun:
    if session.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    run = InvestigationRun(incident_id=incident_id, status=payload.status)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


@app.get("/runs/{run_id}/artifacts", response_model=list[EvidenceArtifact])
def get_run_artifacts(run_id: int, session: SessionDep) -> list[EvidenceArtifact]:
    if session.get(InvestigationRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    return list(
        session.exec(
            select(EvidenceArtifact)
            .where(EvidenceArtifact.run_id == run_id)
            .order_by(EvidenceArtifact.created_at)
        ).all()
    )


@app.post("/runs/{run_id}/artifacts", response_model=EvidenceArtifact, status_code=status.HTTP_201_CREATED)
def create_run_artifact(run_id: int, payload: ArtifactCreate, session: SessionDep) -> EvidenceArtifact:
    if session.get(InvestigationRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    artifact = EvidenceArtifact(run_id=run_id, **payload.model_dump(exclude={"id", "run_id"}))
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


@app.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: int,
    session: SessionDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    if session.get(InvestigationRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    try:
        after_id = max(0, int(last_event_id or 0))
    except ValueError:
        after_id = 0

    async def event_stream():
        async for item in run_event_hub.subscribe(run_id, after_id=after_id):
            yield ServerSentEvent(
                id=str(item.id),
                event=item.event,
                data=json.dumps(item.data, default=str, separators=(",", ":")),
            )
            if item.event in {"report_ready", "run_failed"}:
                break

    return EventSourceResponse(event_stream())
