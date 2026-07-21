from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Incident(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    started_at: datetime = Field(default_factory=utc_now)
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: str = "open"


class InvestigationRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    incident_id: int = Field(foreign_key="incident.id", index=True)
    status: str = "running"
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceArtifact(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="investigationrun.id", index=True)
    tool_name: str
    input_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    output_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class Finding(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="investigationrun.id", index=True)
    kind: str
    content_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    confidence: float
    evidence_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

