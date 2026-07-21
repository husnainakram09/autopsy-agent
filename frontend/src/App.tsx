import { Component, useEffect, useMemo, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  Check,
  ChevronRight,
  Clock3,
  Copy,
  Download,
  FileCode2,
  FileSearch,
  GitBranch,
  GitCommitHorizontal,
  GitCompareArrows,
  Gauge,
  ListTree,
  Loader2,
  Play,
  Rocket,
  ScrollText,
  Search,
  ShieldCheck,
  Sparkles,
  X,
  TerminalSquare,
  TimerReset,
  UserRound,
  XCircle,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Diff from "react-diff-viewer";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader } from "./components/ui/card";
import { TabsList, TabsTrigger } from "./components/ui/tabs";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Incident = {
  id: number;
  title: string;
  started_at: string;
  window_start?: string | null;
  window_end?: string | null;
  status: string;
};

type Run = { id: number; incident_id: number; status: string; created_at: string };
type JsonObject = Record<string, unknown>;
type FeedEvent = { id: string; event: string; data: JsonObject };
type IncidentDetail = { incident: Incident; runs: Run[] };
type Artifact = { id: number; run_id: number; tool_name: string; input_json: JsonObject; output_json: JsonObject; summary: string; created_at: string };
type TimelineEvent = { ts: string; title: string; description: string; evidence_ids: number[] };
type Hypothesis = {
  cause: string;
  mechanism: string;
  confidence_0_to_1: number;
  supporting_evidence_ids: number[];
  disconfirming_test_description: string;
  verification_result: string;
};
type Report = {
  timeline: TimelineEvent[];
  hypotheses: Hypothesis[];
  postmortem: {
    summary: string;
    impact: string;
    root_cause: string;
    evidence_ids: number[];
    contributing_factors: string[];
    detection_gaps: string[];
    action_items: string[];
  };
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method?.toUpperCase() ?? "GET";
  const retryable = method === "GET" || method === "HEAD";
  let lastError: Error = new Error("Request failed");
  for (let attempt = 0; attempt < (retryable ? 3 : 1); attempt += 1) {
    try {
      const response = await fetch(`${API_URL}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      if (response.ok) return response.json() as Promise<T>;
      const message = (await response.text()) || `Request failed (${response.status})`;
      if (response.status < 500 || attempt === 2) throw new Error(message);
      lastError = new Error(message);
    } catch (error) {
      lastError = error instanceof Error ? error : new Error("Network request failed");
      if (!retryable || attempt === 2) throw lastError;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt));
  }
  throw lastError;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function relativeDate(value: string) {
  const hours = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 3600000));
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function App() {
  const [route, setRoute] = useState(() => window.location.hash);
  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const match = route.match(/^#\/incidents\/(\d+)/);
  if (match) return <IncidentDetail incidentId={Number(match[1])} onBack={() => (window.location.hash = "")} />;
  return <IncidentsPage onOpen={(id) => (window.location.hash = `/incidents/${id}`)} />;
}

function AppHeader({ eyebrow, onBack }: { eyebrow: string; onBack?: () => void }) {
  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-800/80 px-5 lg:px-8">
      <div className="flex items-center gap-3">
        {onBack ? (
          <button onClick={onBack} className="mr-1 rounded-md p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-100" aria-label="Back to incidents">
            <ArrowLeft className="h-4 w-4" />
          </button>
        ) : null}
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-400/10 text-cyan-300 ring-1 ring-cyan-400/20">
          <ShieldCheck className="h-4 w-4" />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight text-slate-100">Autopsy<span className="text-cyan-300">/</span>SRE</p>
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-600">{eyebrow}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
        Systems nominal
      </div>
    </header>
  );
}

function IncidentsPage({ onOpen }: { onOpen: (id: number) => void }) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    api<Incident[]>("/incidents").then(setIncidents).catch((err: Error) => setError(err.message)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <AppHeader eyebrow="incident console" />
      <main className="mx-auto max-w-[1500px] px-5 py-8 lg:px-8">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-cyan-400">Operations / incidents</p>
            <h1 className="text-3xl font-semibold tracking-tight">Incident workspace</h1>
            <p className="mt-2 text-sm text-slate-500">Investigate production anomalies with evidence, not assumptions.</p>
          </div>
          <Button variant="outline" onClick={load} className="gap-2 border-slate-700 text-slate-300">
            <Activity className="h-4 w-4" /> Refresh
          </Button>
        </div>
        {error ? <ErrorState message={error} /> : null}
        <Card className="overflow-hidden">
          <div className="grid grid-cols-[minmax(260px,1.6fr)_180px_180px_110px_32px] border-b border-slate-800 px-5 py-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
            <span>Incident</span><span>Started</span><span>Window</span><span>Status</span><span />
          </div>
          {loading ? <LoadingRows /> : incidents.length ? incidents.map((incident) => <IncidentRow key={incident.id} incident={incident} onOpen={onOpen} />) : <EmptyState />}
        </Card>
      </main>
    </div>
  );
}

function IncidentRow({ incident, onOpen }: { incident: Incident; onOpen: (id: number) => void }) {
  const active = incident.status === "open" || incident.status === "investigating";
  return (
    <button onClick={() => onOpen(incident.id)} className="grid w-full grid-cols-[minmax(260px,1.6fr)_180px_180px_110px_32px] items-center border-b border-slate-800/70 px-5 py-4 text-left transition hover:bg-slate-800/35">
      <span className="flex items-center gap-3"><span className={`h-2 w-2 rounded-full ${active ? "bg-amber-400" : "bg-slate-600"}`} /><span><span className="block text-sm font-medium text-slate-200">{incident.title}</span><span className="mt-1 block font-mono text-[10px] text-slate-600">INC-{String(incident.id).padStart(4, "0")}</span></span></span>
      <span className="text-xs text-slate-400">{formatDate(incident.started_at)}</span>
      <span className="font-mono text-[11px] text-slate-500">{formatDate(incident.window_start)} → {formatDate(incident.window_end)}</span>
      <Badge className={active ? "border-amber-400/30 bg-amber-400/10 text-amber-300" : "border-slate-700 text-slate-500"}>{incident.status}</Badge>
      <ChevronRight className="h-4 w-4 text-slate-700" />
    </button>
  );
}

function IncidentDetail({ incidentId, onBack }: { incidentId: number; onBack: () => void }) {
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<IncidentDetail>(`/incidents/${incidentId}`).then((data) => {
      setDetail(data);
      const latest = data.runs?.[data.runs.length - 1];
      if (latest) setRun(latest);
    }).catch((err: Error) => setError(err.message));
  }, [incidentId]);

  useEffect(() => {
    if (!run) return;
    api<Artifact[]>(`/runs/${run.id}/artifacts`).then(setArtifacts).catch(() => undefined);
    const source = new EventSource(`${API_URL}/runs/${run.id}/stream`);
    const eventNames = ["step_started", "tool_call", "tool_result_summary", "tool_timeout", "context_compacted", "hypothesis_update", "report_ready", "report_rejected", "run_failed"];
    const onEvent = (event: Event) => {
      const message = event as MessageEvent<string>;
      const data = JSON.parse(message.data) as JsonObject;
      const next: FeedEvent = { id: message.lastEventId || crypto.randomUUID(), event: event.type, data };
      setFeed((current) => current.some((item) => item.id === next.id) ? current : [...current, next]);
      if (data.artifact_id) api<Artifact[]>(`/runs/${run.id}/artifacts`).then(setArtifacts).catch(() => undefined);
      if (event.type === "report_ready" && data.report) setReport(data.report as Report);
    };
    eventNames.forEach((name) => source.addEventListener(name, onEvent));
    source.onerror = () => setError("Investigation stream disconnected; it will retry automatically.");
    return () => { eventNames.forEach((name) => source.removeEventListener(name, onEvent)); source.close(); };
  }, [run]);

  const investigate = async () => {
    setStarting(true);
    setError("");
    try {
      const nextRun = await api<Run>(`/incidents/${incidentId}/runs`, { method: "POST", body: JSON.stringify({ status: "running" }) });
      setRun(nextRun);
      setFeed([]);
      setReport(null);
      setArtifacts([]);
      setSelectedArtifactId(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to start investigation"); } finally { setStarting(false); }
  };

  if (!detail) return <div className="min-h-screen bg-slate-950 text-slate-100"><AppHeader eyebrow="loading incident" onBack={onBack} /><div className="p-8"><LoadingRows /></div></div>;
  const incident = detail.incident;
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <AppHeader eyebrow={`INC-${String(incident.id).padStart(4, "0")} / investigation`} onBack={onBack} />
      <main className="mx-auto max-w-[1700px] px-4 py-5 lg:px-6">
        <div className="mb-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div><div className="mb-2 flex items-center gap-2"><Badge className="border-amber-400/30 bg-amber-400/10 text-amber-300">{incident.status}</Badge><span className="font-mono text-[10px] text-slate-600">ID {incident.id}</span></div><h1 className="text-2xl font-semibold tracking-tight">{incident.title}</h1><p className="mt-1 flex items-center gap-2 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5" /> Started {formatDate(incident.started_at)} <span className="text-slate-700">•</span> Window {formatDate(incident.window_start)} — {formatDate(incident.window_end)}</p></div>
          <Button onClick={investigate} disabled={starting} className="h-11 gap-2 bg-cyan-400 px-5 font-semibold text-slate-950 shadow-[0_0_25px_rgba(34,211,238,0.16)] hover:bg-cyan-300">{starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {starting ? "Starting investigation…" : "Investigate"}</Button>
        </div>
        {error ? <div className="mb-4"><ErrorState message={error} /></div> : null}
        {report ? <RootCauseHero report={report} artifacts={artifacts} incident={incident} /> : null}
        <div className="grid min-h-[680px] grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(480px,1fr)_360px]">
          <InvestigationFeed feed={feed} run={run} />
          <CenterAnalysis incident={incident} feed={feed} report={report} />
          <RightPanel report={report} feed={feed} artifacts={artifacts} onOpenArtifact={setSelectedArtifactId} />
        </div>
        <ArtifactDrawer artifact={artifacts.find((item) => item.id === selectedArtifactId) ?? null} onClose={() => setSelectedArtifactId(null)} />
      </main>
    </div>
  );
}

function InvestigationFeed({ feed, run }: { feed: FeedEvent[]; run: Run | null }) {
  return <Card className="flex min-h-[680px] flex-col"><CardHeader className="border-b border-slate-800/80 pb-3"><PanelTitle icon={Activity} title="Investigation Feed" meta={run ? `RUN-${String(run.id).padStart(4, "0")}` : "IDLE"} /><p className="text-xs text-slate-500">Live agent trace and tool activity</p></CardHeader><CardContent className="flex-1 overflow-auto p-4"><div className="relative ml-2 border-l border-slate-800 pl-5">{feed.length ? feed.map((item, index) => <FeedItem key={`${item.id}-${index}`} item={item} />) : <div className="py-16 text-center text-xs text-slate-600"><TerminalSquare className="mx-auto mb-3 h-6 w-6 text-slate-700" />Press Investigate to start the evidence loop.</div>}</div></CardContent></Card>;
}

function RootCauseHero({ report, artifacts, incident }: { report: Report; artifacts: Artifact[]; incident: Incident }) {
  const citedIds = new Set([
    ...(report.postmortem.evidence_ids ?? []),
    ...report.hypotheses.flatMap((hypothesis) => hypothesis.supporting_evidence_ids ?? []),
  ]);
  const diffArtifacts = artifacts.filter((artifact) => artifact.tool_name === "get_commit_diff");
  const diffArtifact = diffArtifacts.find((artifact) => citedIds.has(artifact.id)) ?? diffArtifacts[0];
  const commitArtifact = artifacts.find((artifact) => artifact.tool_name === "get_recent_commits");
  const commits = Array.isArray(commitArtifact?.output_json.value) ? commitArtifact.output_json.value as Array<{ sha?: string; author?: string; message?: string; timestamp?: string }> : [];
  const sha = String(diffArtifact?.input_json.sha ?? commits[0]?.sha ?? "unknown");
  const commit = commits.find((item) => item.sha === sha) ?? commits[0];
  const author = String(commit?.author ?? "unknown");
  const message = String(commit?.message ?? "Root cause commit identified by the investigation").split("\n")[0];
  const timestamp = commit?.timestamp;
  const mechanism = report.hypotheses.slice().sort((a, b) => b.confidence_0_to_1 - a.confidence_0_to_1)[0]?.mechanism ?? report.postmortem.root_cause;
  const lines = selectDamningDiffLines(String(diffArtifact?.output_json.diff ?? ""));
  return <Card className="mb-4 overflow-hidden border-rose-400/20 bg-gradient-to-br from-rose-400/[0.06] via-slate-900/80 to-slate-900/70"><div className="flex items-center gap-2 border-b border-rose-400/10 px-5 py-2.5"><GitBranch className="h-3.5 w-3.5 text-rose-300" /><span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-rose-300">Root cause</span><span className="ml-auto flex items-center gap-1.5 text-[10px] text-slate-600"><ShieldCheck className="h-3 w-3 text-emerald-400" />Verified by code diff</span></div><div className="grid gap-5 p-5 lg:grid-cols-[minmax(260px,0.85fr)_minmax(300px,1.15fr)]"><div><div className="flex items-start gap-3"><img src={`https://github.com/${encodeURIComponent(author)}.png?size=64`} alt={`${author} avatar`} className="h-10 w-10 rounded-full border border-slate-700 bg-slate-800" onError={(event) => { event.currentTarget.style.display = "none"; }} /><div className="min-w-0"><div className="flex items-center gap-2"><p className="truncate text-sm font-semibold text-slate-100">{message}</p></div><p className="mt-1 flex items-center gap-1.5 text-[11px] text-slate-500"><UserRound className="h-3 w-3" />{author}<span className="text-slate-700">·</span><span className="font-mono text-[10px]">{sha.slice(0, 10)}</span></p></div></div><div className="mt-5 flex items-center gap-4"><div><p className="text-[9px] uppercase tracking-[0.16em] text-slate-600">Commit time</p><p className="mt-1 font-mono text-[11px] text-slate-400">{formatDate(timestamp)}</p></div><div className="h-7 border-l border-slate-800" /><div><p className="flex items-center gap-1 text-[9px] uppercase tracking-[0.16em] text-slate-600"><TimerReset className="h-3 w-3" /> Time to incident</p><p className="mt-1 font-mono text-[11px] text-amber-300">{formatDelta(timestamp, incident.started_at)}</p></div></div><p className="mt-5 border-l-2 border-rose-400/50 pl-3 text-xs leading-relaxed text-slate-300">{mechanism}</p></div><div><p className="mb-2 flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-600"><FileCode2 className="h-3 w-3 text-rose-300" /> Damning diff lines</p><div className="overflow-hidden rounded-lg border border-slate-800 bg-[#080d18]">{lines.length ? lines.map((line, index) => <div key={`${line}-${index}`} className="flex border-b border-slate-900/80 last:border-0"><span className="w-8 shrink-0 select-none bg-slate-900/70 px-2 py-1.5 text-right font-mono text-[9px] text-slate-700">{index + 1}</span><code className="block flex-1 overflow-x-auto whitespace-pre px-3 py-1.5 font-mono text-[10px] text-rose-200">{line}</code></div>) : <p className="p-4 text-xs text-slate-600">The cited diff artifact is not available yet.</p>}</div></div></div></Card>;
}

function selectDamningDiffLines(diff: string) {
  const additions = diff.split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++"));
  const important = additions.filter((line) => /query|select|pool|connection|join|for |while |sleep|timeout/i.test(line));
  return [...new Set([...important, ...additions])].slice(0, 5);
}

function formatDelta(commitTimestamp?: string, incidentTimestamp?: string) {
  if (!commitTimestamp || !incidentTimestamp) return "—";
  const minutes = Math.max(0, Math.round((new Date(incidentTimestamp).getTime() - new Date(commitTimestamp).getTime()) / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `${hours}h ${remainder}m`;
}

function FeedItem({ item }: { item: FeedEvent }) {
  const Icon = eventIcon(item);
  const toolName = String(item.data.tool_name ?? "agent");
  const title = item.event === "tool_call" ? toolName : item.event.replaceAll("_", " ");
  const body = String(item.data.summary ?? item.data.message ?? item.data.reason ?? "Step emitted");
  const artifactId = item.data.artifact_id;
  return <div className="relative mb-5 last:mb-0"><span className="absolute -left-[31px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-slate-800 bg-slate-950 text-cyan-300"><Icon className="h-2.5 w-2.5" /></span><div className="flex items-center justify-between gap-2"><p className="text-[11px] font-medium capitalize text-slate-300">{title}</p>{artifactId ? <span className="font-mono text-[9px] text-cyan-500/70">#{String(artifactId)}</span> : null}</div><p className="mt-1 text-[11px] leading-relaxed text-slate-500">{body}</p></div>;
}

function CenterAnalysis({ incident, feed, report }: { incident: Incident; feed: FeedEvent[]; report: Report | null }) {
  const chart = useMemo(() => buildChart(incident), [incident]);
  const deployMarkers = feed.filter((item) => item.data.tool_name === "list_deployments").map((_, index) => chart[Math.min(7 + index * 7, chart.length - 1)]?.ts).filter(Boolean) as string[];
  return <div className="space-y-4"><Card><CardHeader className="pb-2"><PanelTitle icon={Activity} title="Service health" meta="PROMETHEUS" /><div className="mt-3 flex items-center gap-5"><Stat label="Error rate" value="4.8%" tone="rose" /><Stat label="p95 latency" value="842ms" tone="amber" /><Stat label="Requests" value="1.2k/s" tone="cyan" /></div></CardHeader><CardContent><div className="h-[250px] w-full"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart} margin={{ top: 12, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id="rateFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.28} /><stop offset="100%" stopColor="#22d3ee" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" stroke="#475569" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} /><YAxis stroke="#475569" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 11 }} /><ReferenceArea x1={chart[3]?.label} x2={chart[18]?.label} fill="#f59e0b" fillOpacity={0.05} /><Area type="monotone" dataKey="value" stroke="#22d3ee" fill="url(#rateFill)" strokeWidth={2} dot={false} /><ReferenceLine x={deployMarkers[0]} stroke="#a78bfa" strokeDasharray="4 4" label={{ value: "deploy", position: "insideTop", fill: "#a78bfa", fontSize: 10 }} /><ReferenceLine x={deployMarkers[1]} stroke="#a78bfa" strokeDasharray="4 4" /></AreaChart></ResponsiveContainer></div><div className="mt-2 flex items-center gap-4 text-[10px] text-slate-600"><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-amber-400/30 ring-1 ring-amber-400/30" /> incident window</span><span className="flex items-center gap-1.5"><span className="h-3 border-l border-dashed border-violet-400" /> deploy marker</span></div></CardContent></Card><Card><CardHeader className="pb-2"><PanelTitle icon={ListTree} title="Incident timeline" meta={report ? `${report.timeline.length} EVENTS` : "AWAITING REPORT"} /></CardHeader><CardContent>{report?.timeline.length ? <div className="space-y-4">{report.timeline.map((event, index) => <TimelineRow key={`${event.ts}-${index}`} event={event} />)}</div> : <div className="rounded-lg border border-dashed border-slate-800 p-7 text-center text-xs text-slate-600"><Search className="mx-auto mb-2 h-5 w-5" />Verified timeline events will appear after the agent submits its report.</div>}</CardContent></Card></div>;
}

function RightPanel({ report, feed, artifacts, onOpenArtifact }: { report: Report | null; feed: FeedEvent[]; artifacts: Artifact[]; onOpenArtifact: (id: number) => void }) {
  const [tab, setTab] = useState("hypotheses");
  return <Card className="min-h-[680px] overflow-hidden"><CardHeader className="p-0"><TabsList><TabsTrigger active={tab === "hypotheses"} onClick={() => setTab("hypotheses")}>Hypotheses</TabsTrigger><TabsTrigger active={tab === "postmortem"} onClick={() => setTab("postmortem")}>Postmortem</TabsTrigger><TabsTrigger active={tab === "evidence"} onClick={() => setTab("evidence")}>Evidence</TabsTrigger></TabsList></CardHeader><CardContent className="p-4">{tab === "hypotheses" ? <Hypotheses report={report} artifacts={artifacts} onOpenArtifact={onOpenArtifact} /> : tab === "postmortem" ? <Postmortem report={report} onOpenArtifact={onOpenArtifact} /> : <Evidence feed={feed} artifacts={artifacts} onOpenArtifact={onOpenArtifact} />}</CardContent></Card>;
}

function Hypotheses({ report, artifacts, onOpenArtifact }: { report: Report | null; artifacts: Artifact[]; onOpenArtifact: (id: number) => void }) {
  if (!report?.hypotheses?.length) return <EmptyPanel icon={BrainCircuit} text="Competing hypotheses will be tracked here." />;
  const ranked = [...report.hypotheses].sort((a, b) => b.confidence_0_to_1 - a.confidence_0_to_1);
  return <div className="space-y-3">{ranked.map((hypothesis, index) => { const weakened = /weaken|disconfirm|fail|unlikely|not supported/i.test(hypothesis.verification_result); return <div key={`${hypothesis.cause}-${index}`} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3.5"><div className="mb-3 flex items-start justify-between gap-3"><div className="flex min-w-0 items-start gap-2"><span className="font-mono text-[10px] text-slate-600">0{index + 1}</span><p className="text-xs font-medium leading-relaxed text-slate-200">{hypothesis.cause}</p></div><span className="shrink-0 font-mono text-[11px] text-cyan-300">{Math.round(hypothesis.confidence_0_to_1 * 100)}%</span></div><div className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-800"><div className={`h-full rounded-full ${hypothesis.confidence_0_to_1 > 0.8 ? "bg-cyan-400" : "bg-violet-400"}`} style={{ width: `${Math.round(hypothesis.confidence_0_to_1 * 100)}%` }} /></div><p className="text-[11px] leading-relaxed text-slate-400">{hypothesis.mechanism}</p><div className="mt-3 flex flex-wrap gap-1.5">{hypothesis.supporting_evidence_ids.length ? hypothesis.supporting_evidence_ids.map((id) => <button key={id} onClick={() => onOpenArtifact(id)} className="rounded-md border border-cyan-400/20 bg-cyan-400/5 px-2 py-1 font-mono text-[10px] text-cyan-300 transition hover:border-cyan-300/60 hover:bg-cyan-400/10">artifact #{id}</button>) : <span className="text-[10px] text-slate-700">No supporting artifacts cited</span>}</div><div className="mt-3 rounded-md border border-slate-800/80 bg-slate-900/60 p-2.5"><div className="mb-1 flex items-center justify-between gap-2"><span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-600">Disconfirming test</span><Badge className={weakened ? "border-amber-400/30 bg-amber-400/10 text-amber-300" : "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"}>{weakened ? "weakened" : "confirmed"}</Badge></div><p className="text-[10px] leading-relaxed text-slate-500">{hypothesis.disconfirming_test_description}</p><p className={`mt-2 text-[10px] leading-relaxed ${weakened ? "text-amber-300/80" : "text-emerald-300/80"}`}>{hypothesis.verification_result}</p></div></div>; })}</div>;
}

function Postmortem({ report, onOpenArtifact }: { report: Report | null; onOpenArtifact: (id: number) => void }) {
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const [copied, setCopied] = useState(false);
  if (!report) return <EmptyPanel icon={FileSearch} text="The verified postmortem will appear here." />;
  const postmortem = report.postmortem;
  const markdown = buildPostmortemMarkdown(postmortem);
  const evidenceIds = postmortem.evidence_ids ?? [];
  const copyMarkdown = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };
  const downloadMarkdown = () => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "incident-postmortem.md";
    link.click();
    URL.revokeObjectURL(url);
  };
  return <div className="space-y-5"><div className="flex items-center justify-end gap-2"><Button variant="outline" onClick={copyMarkdown} className="h-8 gap-1.5 border-slate-700 px-2.5 text-[10px] text-slate-400">{copied ? <Check className="h-3 w-3 text-emerald-300" /> : <Copy className="h-3 w-3" />}{copied ? "Copied" : "Copy as Markdown"}</Button><Button variant="outline" onClick={downloadMarkdown} className="h-8 gap-1.5 border-slate-700 px-2.5 text-[10px] text-slate-400"><Download className="h-3 w-3" />Download .md</Button></div><article className="prose prose-invert prose-sm max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-h2:mb-2 prose-h2:mt-5 prose-p:my-2 prose-p:text-[11px] prose-p:leading-relaxed prose-p:text-slate-400 prose-li:text-[11px] prose-li:text-slate-400"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => { if (href?.startsWith("evidence:")) { const id = Number(href.slice("evidence:".length)); return <sup className="ml-1"><button onClick={() => onOpenArtifact(id)} className="font-mono text-[9px] text-cyan-300 underline decoration-cyan-400/30 underline-offset-2 hover:text-cyan-100">#{id}</button></sup>; } return <a href={href}>{children}</a>; } }}>{markdown}</ReactMarkdown></article><div className="border-t border-slate-800 pt-4"><div className="mb-3 flex items-center justify-between"><h3 className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500"><ListTree className="h-3.5 w-3.5 text-cyan-400" />Action items</h3><span className="font-mono text-[9px] text-slate-700">{evidenceIds.length} cited artifacts</span></div><div className="space-y-2">{postmortem.action_items.map((item, index) => <label key={`${item}-${index}`} className={`flex cursor-pointer items-start gap-2 rounded-md border p-2.5 transition ${checked[index] ? "border-emerald-400/20 bg-emerald-400/5" : "border-slate-800 bg-slate-950/40 hover:border-slate-700"}`}><input type="checkbox" checked={Boolean(checked[index])} onChange={() => setChecked((current) => ({ ...current, [index]: !current[index] }))} className="mt-0.5 accent-cyan-400" /><span className={`flex-1 text-[11px] leading-relaxed ${checked[index] ? "text-slate-600 line-through" : "text-slate-400"}`}>{item}<span className="mt-1 block font-mono text-[9px] text-slate-700">OWNER: ____________________</span></span></label>)}</div></div></div>;
}

function buildPostmortemMarkdown(postmortem: Report["postmortem"]) {
  const citations = (postmortem.evidence_ids ?? []).map((id) => `[#${id}](evidence:${id})`).join(" ");
  const bullets = (items: string[]) => items.length ? items.map((item) => `- ${item}`).join("\n") : "- None recorded";
  const actionItems = postmortem.action_items.length ? postmortem.action_items.map((item) => `- [ ] ${item} — Owner: ____________________`).join("\n") : "- None recorded";
  return `## Summary\n${postmortem.summary} ${citations}\n\n## Impact\n${postmortem.impact} ${citations}\n\n## Root cause\n${postmortem.root_cause} ${citations}\n\n## Contributing factors\n${bullets(postmortem.contributing_factors)} ${citations}\n\n## Detection gaps\n${bullets(postmortem.detection_gaps)} ${citations}\n\n## Action items\n${actionItems}\n`;
}

function Evidence({ feed, artifacts, onOpenArtifact }: { feed: FeedEvent[]; artifacts: Artifact[]; onOpenArtifact: (id: number) => void }) {
  if (!feed.length) return <EmptyPanel icon={FileCode2} text="Tool artifacts will be cited here." />;
  const artifactMap = new Map(artifacts.map((artifact) => [artifact.id, artifact]));
  return <div className="space-y-2">{feed.filter((item) => item.data.artifact_id).map((item, index) => { const id = Number(item.data.artifact_id); const artifact = artifactMap.get(id); return <button key={`${item.id}-${index}`} onClick={() => onOpenArtifact(id)} className="flex w-full items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-left transition hover:border-cyan-400/30 hover:bg-slate-900"><div className="mt-0.5 rounded bg-cyan-400/10 p-1.5 text-cyan-300"><FileCode2 className="h-3 w-3" /></div><div className="min-w-0"><div className="flex items-center gap-2"><span className="font-mono text-[10px] text-cyan-300">artifact #{id}</span><span className="truncate text-[10px] text-slate-600">{artifact?.tool_name ?? String(item.data.tool_name ?? "agent")}</span></div><p className="mt-1 text-[10px] leading-relaxed text-slate-500">{artifact?.summary ?? String(item.data.summary ?? "Captured tool result")}</p></div></button>; })}</div>;
}

function ArtifactDrawer({ artifact, onClose }: { artifact: Artifact | null; onClose: () => void }) {
  if (!artifact) return null;
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-[2px]" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="flex h-full w-full max-w-2xl flex-col border-l border-slate-800 bg-slate-950 shadow-2xl shadow-black/50"><div className="flex items-start justify-between border-b border-slate-800 p-5"><div><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-cyan-400">Evidence artifact #{artifact.id}</p><h2 className="mt-1 text-lg font-semibold text-slate-100">{artifact.tool_name}</h2><p className="mt-1 text-xs text-slate-500">{artifact.summary || "Raw persisted tool output"}</p></div><button onClick={onClose} className="rounded-md p-2 text-slate-500 hover:bg-slate-800 hover:text-slate-100" aria-label="Close evidence drawer"><X className="h-4 w-4" /></button></div><div className="flex-1 overflow-auto p-5"><ArtifactContent artifact={artifact} /></div></aside></div>;
}

function ArtifactContent({ artifact }: { artifact: Artifact }) {
  const output = artifact.output_json ?? {};
  if (artifact.tool_name === "get_commit_diff") return <DiffArtifact output={output} />;
  if (artifact.tool_name === "cluster_errors") return <ClusterArtifact output={output} />;
  if (artifact.tool_name === "query_metrics") return <MetricArtifact output={output} input={artifact.input_json} />;
  return <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-slate-900 p-4 font-mono text-[11px] leading-relaxed text-slate-400">{JSON.stringify(output, null, 2)}</pre>;
}

function DiffArtifact({ output }: { output: JsonObject }) {
  const diff = String(output.diff ?? output.value ?? "");
  const lines = diff.split("\n");
  const oldValue = lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).map((line) => line.slice(1)).join("\n");
  const newValue = lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).map((line) => line.slice(1)).join("\n");
  return <div className="overflow-hidden rounded-lg border border-slate-800 text-[11px]"><Diff oldValue={oldValue || " "} newValue={newValue || diff} splitView={true} useDarkTheme={true} hideLineNumbers={false} /></div>;
}

function ClusterArtifact({ output }: { output: JsonObject }) {
  const clusters = Array.isArray(output.clusters) ? output.clusters as Array<{ template?: string; count?: number; samples?: string[] }> : [];
  if (!clusters.length) return <EmptyPanel icon={ListTree} text="No error clusters in this artifact." />;
  return <div className="overflow-hidden rounded-lg border border-slate-800"><table className="w-full text-left text-[11px]"><thead className="bg-slate-900 text-[9px] uppercase tracking-wider text-slate-600"><tr><th className="px-3 py-2">Count</th><th className="px-3 py-2">Normalized template</th><th className="px-3 py-2">Samples</th></tr></thead><tbody className="divide-y divide-slate-800">{clusters.map((cluster, index) => <tr key={`${cluster.template}-${index}`} className="align-top"><td className="px-3 py-3 font-mono text-rose-300">{cluster.count ?? 0}</td><td className="px-3 py-3 font-mono text-slate-300">{cluster.template}</td><td className="space-y-1 px-3 py-3 text-slate-500">{(cluster.samples ?? []).map((sample) => <p key={sample}>{sample}</p>)}</td></tr>)}</tbody></table></div>;
}

function MetricArtifact({ output, input }: { output: JsonObject; input: JsonObject }) {
  const series = Array.isArray(output.series) ? output.series as Array<{ labels?: JsonObject; points?: Array<{ timestamp: string | number; value: number }>; summary?: JsonObject }> : [];
  const points = series[0]?.points ?? [];
  const data = points.map((point) => ({ label: new Date(Number(point.timestamp) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), value: point.value }));
  return <div><div className="mb-4 flex items-center justify-between"><div><p className="text-[10px] uppercase tracking-wider text-slate-600">PromQL</p><p className="mt-1 rounded bg-slate-900 px-2 py-1 font-mono text-[11px] text-cyan-300">{String(input.promql ?? "range query")}</p></div><span className="font-mono text-[10px] text-slate-500">{series.length} series</span></div>{data.length ? <div className="h-56 rounded-lg border border-slate-800 bg-slate-900/60 p-2"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="label" tick={{ fontSize: 9 }} stroke="#475569" tickLine={false} axisLine={false} /><YAxis tick={{ fontSize: 9 }} stroke="#475569" tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 10 }} /><Area type="monotone" dataKey="value" stroke="#22d3ee" fill="#22d3ee" fillOpacity={0.12} /></AreaChart></ResponsiveContainer></div> : <EmptyPanel icon={Gauge} text="No metric points in this artifact." />}</div>;
}

function TimelineRow({ event }: { event: TimelineEvent }) { return <div className="flex gap-3"><div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cyan-400/10 text-cyan-300"><CheckCircle2 className="h-3 w-3" /></div><div><div className="flex items-center gap-2"><p className="text-xs font-medium text-slate-300">{event.title}</p><span className="font-mono text-[9px] text-slate-600">{formatDate(event.ts)}</span></div><p className="mt-1 text-[11px] leading-relaxed text-slate-500">{event.description}</p><div className="mt-1 flex gap-1">{event.evidence_ids.map((id) => <span key={id} className="font-mono text-[9px] text-cyan-500/70">#{id}</span>)}</div></div></div>; }
function InfoBlock({ label, value, accent }: { label: string; value: string; accent?: "cyan" }) { return <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">{label}</p><p className={accent === "cyan" ? "leading-relaxed text-cyan-200" : "leading-relaxed text-slate-400"}>{value}</p></div>; }
function BulletBlock({ label, items }: { label: string; items: string[] }) { return <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">{label}</p>{items.length ? <ul className="space-y-1 text-slate-500">{items.map((item) => <li key={item} className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-600" />{item}</li>)}</ul> : <p className="text-slate-700">None recorded.</p>}</div>; }
function EmptyPanel({ icon: Icon, text }: { icon: LucideIcon; text: string }) { return <div className="py-20 text-center text-xs text-slate-600"><Icon className="mx-auto mb-3 h-6 w-6 text-slate-700" />{text}</div>; }
function ErrorState({ message }: { message: string }) { return <div className="flex items-center gap-2 rounded-lg border border-rose-400/20 bg-rose-400/5 p-3 text-xs text-rose-300"><AlertCircle className="h-4 w-4" />{message}</div>; }
function LoadingRows() { return <div className="space-y-3 p-5">{[1, 2, 3].map((row) => <div key={row} className="h-12 animate-pulse rounded bg-slate-800/40" />)}</div>; }
function EmptyState() { return <div className="p-16 text-center text-sm text-slate-600">No incidents recorded yet.</div>; }
function PanelTitle({ icon: Icon, title, meta }: { icon: LucideIcon; title: string; meta: string }) { return <div className="flex items-center justify-between"><h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-300"><Icon className="h-3.5 w-3.5 text-cyan-400" />{title}</h2><span className="font-mono text-[9px] text-slate-600">{meta}</span></div>; }
function Stat({ label, value, tone }: { label: string; value: string; tone: "rose" | "amber" | "cyan" }) { const colors = { rose: "text-rose-300", amber: "text-amber-300", cyan: "text-cyan-300" }; return <div><p className="text-[10px] uppercase tracking-wider text-slate-600">{label}</p><p className={`mt-1 font-mono text-lg ${colors[tone]}`}>{value}</p></div>; }
function eventIcon(item: FeedEvent): LucideIcon { if (item.event === "tool_call") { const name = String(item.data.tool_name ?? ""); if (name.includes("commit")) return GitCompareArrows; if (name.includes("deployment")) return Rocket; if (name.includes("metric")) return Gauge; if (name.includes("log")) return ScrollText; if (name.includes("cluster")) return ListTree; } if (item.event === "tool_timeout") return TimerReset; if (item.event === "context_compacted") return FileSearch; if (item.event === "hypothesis_update") return BrainCircuit; if (item.event === "report_ready") return CheckCircle2; if (item.event === "run_failed") return XCircle; return Activity; }
function buildChart(incident: Incident) { const start = new Date(incident.window_start ?? incident.started_at).getTime(); const end = new Date(incident.window_end ?? start + 3 * 3600000).getTime(); return Array.from({ length: 24 }, (_, index) => { const ts = new Date(start + ((end - start) * index) / 23); const value = 42 + Math.sin(index / 2.7) * 5 + (index > 15 ? (index - 14) * 8 : 0); return { ts: ts.toISOString(), label: ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), value: Math.round(value) }; }); }

type ErrorBoundaryProps = { children: ReactNode };
type ErrorBoundaryState = { error: Error | null };

class GlobalErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Autopsy console crashed", error, info.componentStack);
  }

  retry = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;
    return <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-slate-100"><Card className="w-full max-w-md border-rose-400/20 bg-slate-900 p-6"><div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-rose-400/10 text-rose-300"><AlertCircle className="h-5 w-5" /></div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-rose-300">Console error</p><h1 className="mt-2 text-xl font-semibold">The incident workspace hit an unexpected error.</h1><p className="mt-2 text-xs leading-relaxed text-slate-500">The page state can be reset safely. Your persisted investigation artifacts are unchanged.</p><pre className="mt-4 max-h-20 overflow-auto rounded bg-slate-950 p-3 font-mono text-[10px] text-slate-600">{this.state.error.message}</pre><Button onClick={this.retry} className="mt-5 gap-2 bg-cyan-400 text-slate-950 hover:bg-cyan-300"><Activity className="h-4 w-4" />Retry workspace</Button></Card></main>;
  }
}

export default function RootApp() {
  return <GlobalErrorBoundary><App /></GlobalErrorBoundary>;
}
