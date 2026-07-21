from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlmodel import Session

from ..models import EvidenceArtifact, InvestigationRun


def _json_object(value: Any) -> dict[str, Any]:
    """Keep artifact columns object-shaped while retaining scalar/list results."""
    if isinstance(value, dict):
        return value
    return {"value": value}


def record_artifact(
    session: Session,
    run_id: int,
    tool_name: str,
    input_json: Any,
    output_json: Any,
    summary: str = "",
) -> EvidenceArtifact:
    if session.get(InvestigationRun, run_id) is None:
        raise ValueError(f"Investigation run {run_id} does not exist")
    artifact = EvidenceArtifact(
        run_id=run_id,
        tool_name=tool_name,
        input_json=_json_object(input_json),
        output_json=_json_object(output_json),
        summary=summary,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


async def run_tool_with_artifact(
    session: Session,
    run_id: int,
    tool_name: str,
    input_json: Any,
    operation: Callable[[], Awaitable[Any]],
    summary: str = "",
) -> tuple[Any, EvidenceArtifact]:
    """Run a tool and return both its result and its persisted artifact."""
    try:
        output = await operation()
    except Exception as exc:
        artifact = record_artifact(
            session,
            run_id,
            tool_name,
            input_json,
            {"error": str(exc), "error_type": type(exc).__name__},
            summary or "Tool call failed",
        )
        raise ToolExecutionError(str(exc), artifact, exc) from exc
    artifact = record_artifact(session, run_id, tool_name, input_json, output, summary)
    return output, artifact


async def run_tool(
    session: Session,
    run_id: int,
    tool_name: str,
    input_json: Any,
    operation: Callable[[], Awaitable[Any]],
    summary: str = "",
) -> Any:
    """Run a tool and persist both successful and failed calls as evidence."""
    output, _ = await run_tool_with_artifact(
        session, run_id, tool_name, input_json, operation, summary
    )
    return output


class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, artifact: EvidenceArtifact, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.artifact = artifact
        self.cause = cause
