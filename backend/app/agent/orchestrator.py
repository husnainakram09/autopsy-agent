from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from .events import RunEventHub, run_event_hub
from ..models import EvidenceArtifact, Finding, Incident, InvestigationRun
from ..services.evidence import ToolExecutionError, record_artifact, run_tool_with_artifact
from ..tools.github import GitHubClient
from ..tools.logs import LokiClient, cluster_errors
from ..tools.metrics import PrometheusClient


SYSTEM_PROMPT = """You are an SRE incident investigator. Be precise, skeptical, and evidence-driven.
Use the investigation method: plan → gather → hypothesize → verify → report.
Start by stating a concise plan. Gather evidence with the available tools, then state
explicit hypotheses and test them with independent evidence. Revise hypotheses when
evidence contradicts them. Cite persisted evidence using artifact IDs such as
artifact_id=42. Do not report a root cause without verification. End only by calling
submit_report with a complete structured report. Every evidence ID in the report must
refer to an artifact returned by a previous tool call in this run.
"""


INVESTIGATION_POLICY = """You are an expert SRE investigating a production incident. Use blameless language,
be precise, skeptical, and evidence-driven. Prefer fewer verified claims over exhaustive
speculation. Cite an artifact ID for every claim in your reasoning and final report.

Investigation method:
1. Establish the incident window from metrics before doing anything else.
2. Correlate deploy and commit timing with anomaly onset. Treat timing correlation as a
   lead, never as proof.
3. Generate 2–4 competing hypotheses. For each hypothesis, state the evidence that would
   disprove it, then run the query or inspection that tests that disconfirming evidence.
4. Assign confidence above 0.8 only when the actual code diff was inspected and it
   mechanistically explains the observed errors.
5. Report only verified conclusions, with artifact IDs for every claim. Use blameless
   language throughout.

Distinguish failure modes carefully: a downstream-timeout incident presents as intermittent
502s with dependency latency clustering around the client timeout and a diff changing the
HTTP timeout; an N+1 incident presents as query volume and latency growing with result size,
often alongside database pool pressure. Do not call one the other without metrics, logs, and
the relevant code diff.

Start by stating a concise plan, but the first evidence-gathering action must establish
the metric window. If a tool times out, treat the timeout as an observed limitation,
record it in your reasoning, and proceed with partial evidence using another signal;
never stall waiting for the same tool indefinitely. Revise hypotheses when evidence
contradicts them. End only by calling submit_report with a complete structured report.
Every evidence ID in the report must
refer to a prior, non-report artifact returned by a tool call in this run.
"""
SYSTEM_PROMPT = INVESTIGATION_POLICY


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimelineEvent(StrictSchema):
    ts: datetime
    title: str
    description: str
    evidence_ids: list[int]


class Hypothesis(StrictSchema):
    cause: str
    mechanism: str
    confidence_0_to_1: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[int]
    disconfirming_test_description: str
    verification_result: str


class Postmortem(StrictSchema):
    summary: str
    impact: str
    root_cause: str
    evidence_ids: list[int]
    contributing_factors: list[str]
    detection_gaps: list[str]
    action_items: list[str]


class InvestigationReport(StrictSchema):
    timeline: list[TimelineEvent]
    hypotheses: list[Hypothesis]
    postmortem: Postmortem


SUBMIT_REPORT_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "submit_report",
    "description": "Submit the final verified incident investigation report.",
    "parameters": InvestigationReport.model_json_schema(),
    "strict": True,
}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_recent_commits",
        "description": "List repository commits in a time window, including changed files.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "since": {"type": ["string", "null"]},
                "until": {"type": ["string", "null"]},
            },
            "required": ["repo", "since", "until"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_commit_diff",
        "description": "Get the unified diff for one commit.",
        "parameters": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "sha": {"type": "string"}},
            "required": ["repo", "sha"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_deployments",
        "description": "List deployments for a repository after a timestamp.",
        "parameters": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "since": {"type": ["string", "null"]}},
            "required": ["repo", "since"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "query_metrics",
        "description": "Query a Prometheus range and return compact statistics and spikes.",
        "parameters": {
            "type": "object",
            "properties": {
                "promql": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "step": {"type": ["string", "number"]},
            },
            "required": ["promql", "start", "end", "step"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "query_logs",
        "description": "Query Loki logs for a time window with a compact result limit.",
        "parameters": {
            "type": "object",
            "properties": {
                "logql": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["logql", "start", "end", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "cluster_errors",
        "description": "Group similar error log entries by normalized message template.",
        "parameters": {
            "type": "object",
            "properties": {"entries": {"type": "array", "items": {"type": "object"}}},
            "required": ["entries"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    SUBMIT_REPORT_TOOL,
]


class InvestigationOrchestrator:
    def __init__(
        self,
        *,
        openai_client: AsyncOpenAI | None = None,
        github_client: GitHubClient | None = None,
        prometheus_client: PrometheusClient | None = None,
        loki_client: LokiClient | None = None,
        event_hub: RunEventHub | None = None,
        model: str | None = None,
        max_iterations: int = 25,
        watchdog_seconds: float = 300.0,
        conversation_token_threshold: int = 24000,
    ) -> None:
        self.openai = openai_client or AsyncOpenAI()
        self.github = github_client or GitHubClient()
        self.prometheus = prometheus_client or PrometheusClient()
        self.loki = loki_client or LokiClient()
        self.event_hub = event_hub or run_event_hub
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6")
        self.max_iterations = min(max(1, max_iterations), 25)
        self.watchdog_seconds = watchdog_seconds
        self.conversation_token_threshold = conversation_token_threshold

    async def close(self) -> None:
        await self.github.close()
        await self.prometheus.close()
        await self.loki.close()
        await self.openai.close()

    async def investigate(
        self,
        session: Session,
        incident: Incident,
        run: InvestigationRun,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run an investigation with a hard watchdog and partial-report salvage."""
        try:
            async with asyncio.timeout(self.watchdog_seconds):
                async for event in self._investigate(session, incident, run):
                    yield event
        except TimeoutError:
            report, artifact = self._salvage_partial_report(session, run)
            yield await self._emit(
                run.id,
                "tool_summary",
                {
                    "tool_name": "watchdog",
                    "artifact_id": artifact.id,
                    "summary": "Five-minute watchdog stopped the run; partial evidence was salvaged.",
                },
            )
            yield await self._emit(
                run.id,
                "report_submitted",
                {"partial": True, "artifact_id": artifact.id, "report": report},
            )
        finally:
            await self.close()

    async def _investigate(
        self,
        session: Session,
        incident: Incident,
        run: InvestigationRun,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run an investigation and yield SSE-ready event dictionaries."""
        conversation: list[Any] = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "incident_id": incident.id,
                        "title": incident.title,
                        "started_at": self._json_value(incident.started_at),
                        "window_start": self._json_value(incident.window_start),
                        "window_end": self._json_value(incident.window_end),
                        "status": incident.status,
                    },
                    separators=(",", ":"),
                ),
            }
        ]
        yield await self._emit(run.id, "plan_update", {"message": "Investigation started; awaiting the agent plan."})
        report_retries = 0

        try:
            for iteration in range(self.max_iterations):
                if await self._compact_conversation(conversation):
                    yield await self._emit(
                        run.id,
                        "context_compacted",
                        {"message": "Conversation context was summarized to stay within the token budget."},
                    )
                response = await self.openai.responses.create(
                    model=self.model,
                    instructions=SYSTEM_PROMPT,
                    input=conversation,
                    tools=TOOL_DEFINITIONS,
                )
                output_items = list(response.output or [])
                conversation.extend(output_items)
                for item in output_items:
                    if getattr(item, "type", None) == "message":
                        text = self._response_text(item)
                        if text:
                            event_type = "hypothesis_change" if "hypothes" in text.lower() else "plan_update"
                            yield await self._emit(run.id, event_type, {"iteration": iteration + 1, "message": text})

                function_calls = [item for item in output_items if getattr(item, "type", None) == "function_call"]
                if not function_calls:
                    yield await self._emit(
                        run.id,
                        "plan_update",
                        {"iteration": iteration + 1, "message": "The agent returned no tool call; continuing toward submit_report."},
                    )
                    continue

                for call in function_calls:
                    name = call.name
                    arguments = json.loads(call.arguments or "{}")
                    yield await self._emit(
                        run.id,
                        "tool_call",
                        {"iteration": iteration + 1, "tool_name": name, "input": arguments},
                    )
                    if name not in {"query_metrics", "submit_report"} and not self._metric_window_established(session, run):
                        guard_message = "Establish the incident window with query_metrics before using other tools."
                        artifact = record_artifact(
                            session,
                            run.id,
                            name,
                            arguments,
                            {"error": guard_message},
                            "Tool call deferred until the metric window is established.",
                        )
                        yield await self._emit(
                            run.id,
                            "tool_summary",
                            {"tool_name": name, "artifact_id": artifact.id, "summary": artifact.summary},
                        )
                        conversation.append(
                            {
                                "type": "function_call_output",
                                "call_id": call.call_id,
                                "output": json.dumps(
                                    {"accepted": False, "artifact_id": artifact.id, "error": guard_message},
                                    separators=(",", ":"),
                                ),
                            }
                        )
                        continue
                    if name == "submit_report":
                        report, validation_error = self._validate_report(session, run, arguments)
                        if validation_error is not None:
                            report_retries += 1
                            artifact = record_artifact(
                                session,
                                run.id,
                                "submit_report",
                                {"run_id": run.id},
                                arguments,
                                f"Rejected report: {validation_error}",
                            )
                            yield await self._emit(
                                run.id,
                                "tool_summary",
                                {
                                    "tool_name": name,
                                    "artifact_id": artifact.id,
                                    "summary": artifact.summary,
                                },
                            )
                            if report_retries > 2:
                                run.status = "failed"
                                session.add(run)
                                session.commit()
                                yield await self._emit(
                                    run.id,
                                    "run_failed",
                                    {"reason": "submit_report remained invalid after 2 retries."},
                                )
                                return
                            correction = (
                                f"submit_report was rejected: {validation_error}. "
                                "Call submit_report again with a corrected complete payload."
                            )
                            conversation.append(
                                {
                                    "type": "function_call_output",
                                    "call_id": call.call_id,
                                    "output": json.dumps(
                                        {
                                            "accepted": False,
                                            "artifact_id": artifact.id,
                                            "error": correction,
                                        },
                                        separators=(",", ":"),
                                    ),
                                }
                            )
                            yield await self._emit(
                                run.id,
                                "report_rejected",
                                {
                                    "retry": report_retries,
                                    "max_retries": 2,
                                    "artifact_id": artifact.id,
                                    "reason": correction,
                                },
                            )
                            continue

                        artifact = self._persist_report(session, run, report)
                        run.status = "completed"
                        session.add(run)
                        session.commit()
                        yield await self._emit(
                            run.id,
                            "tool_summary",
                            {
                                "tool_name": name,
                                "artifact_id": artifact.id,
                                "summary": report.postmortem.summary,
                            },
                        )
                        yield await self._emit(
                            run.id,
                            "report_submitted",
                            {"artifact_id": artifact.id, "report": report.model_dump(mode="json")},
                        )
                        return

                    try:
                        result, artifact = await run_tool_with_artifact(
                            session,
                            run.id,
                            name,
                            arguments,
                            lambda: self._dispatch(name, arguments),
                            summary=self._tool_summary(name, arguments),
                        )
                    except ToolExecutionError as exc:
                        artifact = exc.artifact
                        timed_out = isinstance(exc.cause, (httpx.TimeoutException, TimeoutError))
                        result = {
                            "error": str(exc),
                            "artifact_id": artifact.id,
                            "timed_out": timed_out,
                            "partial_evidence": True,
                            "next_step": "Proceed with partial evidence and test the hypothesis using another signal.",
                        }
                        if timed_out:
                            yield await self._emit(
                                run.id,
                                "tool_timeout",
                                {
                                    "tool_name": name,
                                    "artifact_id": artifact.id,
                                    "summary": "Tool timed out; the agent should proceed with partial evidence.",
                                },
                            )
                        yield await self._emit(
                            run.id,
                            "tool_summary",
                            {"tool_name": name, "artifact_id": artifact.id, "summary": "Tool call failed."},
                        )
                    else:
                        artifact.summary = self._summarize_result(name, result)
                        session.add(artifact)
                        session.commit()
                        yield await self._emit(
                            run.id,
                            "tool_summary",
                            {"tool_name": name, "artifact_id": artifact.id, "summary": artifact.summary},
                        )
                    conversation.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(
                                {"artifact_id": artifact.id, "result": result},
                                default=str,
                                separators=(",", ":"),
                            ),
                        }
                    )
        except asyncio.CancelledError:
            raise
        run.status = "failed"
        session.add(run)
        session.commit()
        yield await self._emit(run.id, "run_failed", {"reason": "Maximum tool-call iterations reached."})

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "get_recent_commits":
            return await self.github.list_commits(arguments["repo"], arguments["since"], arguments["until"])
        if name == "get_commit_diff":
            return {"diff": await self.github.get_commit_diff(arguments["repo"], arguments["sha"])}
        if name == "list_deployments":
            return await self.github.list_deployments(arguments["repo"], arguments["since"])
        if name == "query_metrics":
            return await self.prometheus.query_range(
                arguments["promql"], arguments["start"], arguments["end"], arguments["step"]
            )
        if name == "query_logs":
            return await self.loki.query_logs(
                arguments["logql"], arguments["start"], arguments["end"], arguments["limit"]
            )
        if name == "cluster_errors":
            return {"clusters": cluster_errors(arguments["entries"])}
        raise ValueError(f"Unknown investigation tool: {name}")

    async def _compact_conversation(self, conversation: list[Any]) -> bool:
        estimated_tokens = len(json.dumps(conversation, default=str, separators=(",", ":"))) // 4
        if estimated_tokens <= self.conversation_token_threshold:
            return False
        raw_context = json.dumps(conversation, default=str, separators=(",", ":"))
        try:
            response = await self.openai.responses.create(
                model=self.model,
                instructions=(
                    "Summarize this SRE investigation context compactly. Preserve artifact IDs, "
                    "metric-window facts, hypotheses, disconfirming tests, and unresolved questions."
                ),
                input=[{"role": "user", "content": raw_context}],
                tools=[],
            )
            summary = getattr(response, "output_text", "") or "Context summary unavailable."
        except Exception:
            summary = "Prior context was compacted locally; rely on the persisted artifact IDs below."
        conversation[:] = [
            {"role": "user", "content": f"COMPACTED INVESTIGATION CONTEXT:\n{summary}"},
            *conversation[-6:],
        ]
        return True

    def _salvage_partial_report(
        self,
        session: Session,
        run: InvestigationRun,
    ) -> tuple[dict[str, Any], EvidenceArtifact]:
        prior_ids = [
            artifact_id
            for artifact_id in session.exec(
                select(EvidenceArtifact.id).where(EvidenceArtifact.run_id == run.id)
            ).all()
            if artifact_id is not None
        ]
        report = {
            "timeline": [],
            "hypotheses": [],
            "postmortem": {
                "summary": "Investigation stopped by the five-minute watchdog; this is a partial report.",
                "impact": "Impact remains unconfirmed from the evidence gathered so far.",
                "root_cause": "Root cause remains unconfirmed; review the cited artifacts before taking action.",
                "evidence_ids": prior_ids,
                "contributing_factors": [],
                "detection_gaps": ["Investigation exceeded the run watchdog window."],
                "action_items": ["Resume investigation using the salvaged artifacts."],
            },
        }
        artifact = record_artifact(
            session,
            run.id,
            "watchdog",
            {"watchdog_seconds": self.watchdog_seconds},
            report,
            "Partial report salvaged after watchdog timeout.",
        )
        finding = Finding(
            run_id=run.id,
            kind="partial_incident_report",
            content_json=report,
            confidence=0.0,
            evidence_ids=prior_ids,
        )
        session.add(finding)
        run.status = "timed_out"
        session.add(run)
        session.commit()
        return report, artifact

    @staticmethod
    def _validate_report(
        session: Session,
        run: InvestigationRun,
        payload: dict[str, Any],
    ) -> tuple[InvestigationReport | None, str | None]:
        try:
            report = InvestigationReport.model_validate(payload)
        except ValueError as exc:
            return None, f"report schema validation failed: {exc}"

        metric_artifacts = session.exec(
            select(EvidenceArtifact.id).where(
                EvidenceArtifact.run_id == run.id,
                EvidenceArtifact.tool_name == "query_metrics",
            )
        ).all()
        if not metric_artifacts:
            return None, "the incident window must be established with query_metrics before submitting a report"

        artifact_ids = {
            artifact_id
            for artifact_id in session.exec(
                select(EvidenceArtifact.id).where(
                    EvidenceArtifact.run_id == run.id,
                    EvidenceArtifact.tool_name != "submit_report",
                )
            ).all()
            if artifact_id is not None
        }
        referenced_ids = {
            evidence_id
            for event in report.timeline
            for evidence_id in event.evidence_ids
        }
        referenced_ids.update(
            evidence_id
            for hypothesis in report.hypotheses
            for evidence_id in hypothesis.supporting_evidence_ids
        )
        referenced_ids.update(report.postmortem.evidence_ids)
        missing_ids = sorted(referenced_ids - artifact_ids)
        if missing_ids:
            return None, f"evidence_ids reference nonexistent artifacts: {missing_ids}"
        return report, None

    @staticmethod
    def _metric_window_established(session: Session, run: InvestigationRun) -> bool:
        return session.exec(
            select(EvidenceArtifact.id).where(
                EvidenceArtifact.run_id == run.id,
                EvidenceArtifact.tool_name == "query_metrics",
            )
        ).first() is not None

    @staticmethod
    def _persist_report(session: Session, run: InvestigationRun, report: InvestigationReport):
        report_json = report.model_dump(mode="json")
        artifact = record_artifact(
            session,
            run.id,
            "submit_report",
            {"run_id": run.id},
            report_json,
            report.postmortem.summary,
        )
        confidence = max(
            (hypothesis.confidence_0_to_1 for hypothesis in report.hypotheses),
            default=0.0,
        )
        evidence_ids = sorted(
            {
                evidence_id
                for event in report.timeline
                for evidence_id in event.evidence_ids
            }
            | {
                evidence_id
                for hypothesis in report.hypotheses
                for evidence_id in hypothesis.supporting_evidence_ids
            }
            | set(report.postmortem.evidence_ids)
        )
        finding = Finding(
            run_id=run.id,
            kind="incident_report",
            content_json=report_json,
            confidence=confidence,
            evidence_ids=evidence_ids,
        )
        session.add(finding)
        session.commit()
        return artifact

    @staticmethod
    def _tool_summary(name: str, arguments: dict[str, Any]) -> str:
        return f"{name} completed for {', '.join(str(key) for key in arguments)}."

    @staticmethod
    def _summarize_result(name: str, result: Any) -> str:
        if name == "query_metrics" and isinstance(result, dict):
            series = result.get("series", [])
            spikes = sum(len(item.get("summary", {}).get("spikes", [])) for item in series)
            return f"Returned {len(series)} metric series with {spikes} detected spikes."
        if name == "query_logs" and isinstance(result, list):
            return f"Returned {len(result)} log entries."
        if name == "cluster_errors" and isinstance(result, dict):
            return f"Found {len(result.get('clusters', []))} error clusters."
        if isinstance(result, list):
            return f"Returned {len(result)} records."
        if isinstance(result, dict):
            return f"Returned fields: {', '.join(list(result)[:8])}."
        return f"Returned {str(result)[:200]}"

    @staticmethod
    def _response_text(item: Any) -> str:
        content = getattr(item, "content", None) or []
        return "\n".join(
            str(getattr(part, "text", ""))
            for part in content
            if getattr(part, "type", None) == "output_text"
        ).strip()

    @staticmethod
    def _json_value(value: Any) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else value

    async def _emit(self, run_id: int, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        event = self._event(event_type, data)
        await self.event_hub.publish(run_id, event_type, data)
        return event

    @staticmethod
    def _event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"event": event_type, "data": data}


InvestigationAgent = InvestigationOrchestrator
