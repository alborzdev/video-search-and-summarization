// SPDX-License-Identifier: MIT

import { formatMemory, healthLabel, type SystemHealth } from "./systemHealth";
import {
  IconBellCog,
  IconBolt,
  IconCheck,
  IconCpu,
  IconDatabase,
  IconDeviceDesktopAnalytics,
  IconRefresh,
  IconServer,
  IconShieldLock,
  IconVideo,
} from "@tabler/icons-react";
import React, { ReactNode } from "react";
import type {
  WorkloadAdmissions,
  WorkloadClass,
} from "../../server/vision/workloadAdmission";
import type {
  IndexCoverageStatus,
  RecordingCoverageStatus,
  SearchCoverageSnapshot,
} from "../../server/vision/searchCoverage";

export type SystemPanel = "overview" | "rules" | "sources";

interface SystemWorkspaceProps {
  health: SystemHealth | null;
  onPanelChange: (panel: SystemPanel) => void;
  onRefreshHealth: () => void;
  panel: SystemPanel;
  rules: ReactNode;
  searchCoverage: SearchCoverageSnapshot | null;
  searchCoverageUnavailable: boolean;
  sources: ReactNode;
  workloadAdmissions: WorkloadAdmissions | null;
  workloadCheckedAt: string | null;
}

const WORKLOAD_ROWS: Array<{
  detail: string;
  key: WorkloadClass;
  label: string;
}> = [
  {
    detail: "Inspect the recent visual context for one operator question.",
    key: "current_visual_question",
    label: "Current visual question",
  },
  {
    detail: "Ground a briefing in the exact clips selected as evidence.",
    key: "evidence_analysis",
    label: "Evidence synthesis",
  },
  {
    detail: "Continuously verify one scene condition with visual reasoning.",
    key: "live_vlm_alert",
    label: "Continuous visual alert",
  },
  {
    detail: "Build or extend source-scoped caption and GraphRAG history.",
    key: "long_video_history_build",
    label: "History build",
  },
  {
    detail: "Estimate a calibrated multi-camera group as a specialist workflow.",
    key: "calibration",
    label: "Camera calibration",
  },
  {
    detail: "Analyze an audio lane only after device-specific qualification.",
    key: "experimental_audio",
    label: "Audio intelligence",
  },
];

function admissionLabel(decision: "allow" | "block" | "queue"): string {
  if (decision === "allow") return "Available";
  if (decision === "queue") return "Waits for lane";
  return "Unavailable";
}

function indexCoverageLabel(status: IndexCoverageStatus): string {
  if (status === "indexed") return "Searchable";
  if (status === "not-indexed") return "No semantic index";
  return "Index unknown";
}

function recordingCoverageLabel(status: RecordingCoverageStatus): string {
  if (status === "retained") return "Retained media";
  if (status === "expired") return "Media expired";
  return "Video I/O unknown";
}

function timeLabel(value: string | null): string | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : null;
}

function metricValue(value: string, label: string) {
  return (
    <div className="vi-system-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function SystemWorkspace({
  health,
  onPanelChange,
  onRefreshHealth,
  panel,
  rules,
  searchCoverage,
  searchCoverageUnavailable,
  sources,
  workloadAdmissions,
  workloadCheckedAt,
}: SystemWorkspaceProps) {
  const runningServices = health?.services.filter((service) => service.ok).length ?? 0;
  const totalServices = health?.services.length ?? 0;
  return (
    <section className="vi-system-workspace">
      <div className="vi-page-intro vi-system-intro">
        <div>
          <span className="vi-eyebrow">Data boundary: on device</span>
          <h1>{panel === "overview" ? "Running locally on the edge" : panel === "sources" ? "Sources" : "Alert rules"}</h1>
          <p>
            {panel === "overview"
              ? "Live service health and hardware measurements from this NVIDIA Thor."
              : panel === "sources"
              ? "Connect cameras and recordings, control analysis, and manage generated intelligence."
              : "Define the live conditions that should be verified and surfaced to operators."}
          </p>
        </div>
        {panel === "overview" && (
          <button className="vi-system-refresh" type="button" onClick={onRefreshHealth}>
            <IconRefresh size={17} /> Refresh health
          </button>
        )}
      </div>

      <nav className="vi-system-tabs" aria-label="System">
        <button
          className={panel === "overview" ? "is-active" : ""}
          type="button"
          onClick={() => onPanelChange("overview")}
        >
          <IconCpu size={18} /> Edge system
        </button>
        <button
          className={panel === "sources" ? "is-active" : ""}
          type="button"
          onClick={() => onPanelChange("sources")}
        >
          <IconVideo size={18} /> Sources
        </button>
        <button
          className={panel === "rules" ? "is-active" : ""}
          type="button"
          onClick={() => onPanelChange("rules")}
        >
          <IconBellCog size={18} /> Alert rules
        </button>
      </nav>

      {panel === "overview" && (
        <div className="vi-system-overview">
          <article className="vi-system-hero">
            <div className="vi-system-hardware">
              <div className="vi-system-device">
                <span>CT AI LABS</span>
                <strong>NVIDIA</strong>
                <i>THOR</i>
              </div>
              <div className="vi-system-local-badge">
                <IconShieldLock size={19} /> Local inference boundary
              </div>
            </div>
            <div className="vi-system-proof-copy">
              <span className="vi-eyebrow">Local processing</span>
              <h2>Video becomes searchable intelligence without leaving the device.</h2>
              <p>
                Video I/O, embedding, retrieval, visual reasoning, synthesis, and analytics are connected through the local Thor runtime.
              </p>
              <div className={`vi-system-health-state is-${health?.status ?? "offline"}`}>
                <span />
                <div>
                  <strong>{health ? healthLabel(health.status) : "Checking system"}</strong>
                  <em>{health ? `${runningServices} of ${totalServices} services ready` : "Reading local health"}</em>
                </div>
              </div>
            </div>
          </article>

          <div className="vi-system-metrics-grid">
            {metricValue(
              health?.thor?.activeStreams == null
                ? "Unavailable"
                : String(health.thor.activeStreams),
              "Connected video sources"
            )}
            {metricValue(
              health?.thor?.gpuTemperatureC == null
                ? "Unavailable"
                : `${health.thor.gpuTemperatureC.toFixed(0)}°C`,
              "GPU temperature"
            )}
            {metricValue(
              health?.thor?.powerWatts == null
                ? "Unavailable"
                : `${health.thor.powerWatts.toFixed(1)} W`,
              "GPU power"
            )}
            {metricValue(
              health?.thor
                ? `${formatMemory(health.thor.memoryUsedBytes)} / ${formatMemory(
                    health.thor.memoryTotalBytes
                  )}`
                : "Unavailable",
              "Shared memory"
            )}
          </div>

          <article className="vi-compute-plan">
            <div className="vi-system-section-heading">
              <div>
                <span className="vi-eyebrow">Compute admission</span>
                <h2>What Thor can run now</h2>
              </div>
              <span>
                Read-only plan ·{" "}
                {workloadCheckedAt
                  ? new Date(workloadCheckedAt).toLocaleTimeString()
                  : "checking"}
              </span>
            </div>
            <p>
              Expensive visual work shares one local Cosmos lane. This plan
              reports current ownership and qualification; it never starts,
              stops, or pre-empts a workload.
            </p>
            <div className="vi-admission-list">
              {WORKLOAD_ROWS.map((row) => {
                const admission = workloadAdmissions?.[row.key];
                const decision = admission?.decision ?? "queue";
                return (
                  <div className={`is-${decision}`} key={row.key}>
                    <span>
                      {decision === "allow" ? (
                        <IconCheck size={15} />
                      ) : decision === "queue" ? (
                        <IconBolt size={15} />
                      ) : (
                        <IconShieldLock size={15} />
                      )}
                    </span>
                    <div>
                      <strong>{row.label}</strong>
                      <small>{row.detail}</small>
                    </div>
                    <em>{admission ? admissionLabel(decision) : "Checking"}</em>
                    <p>
                      {admission?.explanation ??
                        "Reading local lane ownership and telemetry…"}
                    </p>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="vi-search-coverage">
            <div className="vi-system-section-heading">
              <div>
                <span className="vi-eyebrow">Search + retention coverage</span>
                <h2>What remains usable as evidence</h2>
              </div>
              <span>
                {searchCoverage
                  ? `${
                      searchCoverageUnavailable
                        ? "Last complete observation"
                        : "Observed"
                    } ${new Date(searchCoverage.generatedAt).toLocaleTimeString()}`
                  : "Checking sources"}
              </span>
            </div>
            {searchCoverage ? (
              <>
                <p>
                  {searchCoverage.summary.indexedSources} of{" "}
                  {searchCoverage.summary.configuredSources} configured sources have
                  searchable semantic moments. {searchCoverage.summary.retainedSources} have
                  a retained recording window. These are source counts, not an
                  estimated coverage percentage.
                </p>
                <div className="vi-search-coverage-list">
                  {searchCoverage.sources.map((source) => {
                    const indexedAt = timeLabel(source.lastSemanticAt);
                    const retainedUntil = timeLabel(source.timelineEnd);
                    return (
                      <article key={source.sensorId}>
                        <div className="vi-search-coverage-source">
                          <strong>{source.name}</strong>
                          <small>{source.sensorId}</small>
                        </div>
                        <div className="vi-search-coverage-states">
                          <span className={`is-${source.indexStatus}`}>
                            {indexCoverageLabel(source.indexStatus)}
                          </span>
                          <span className={`is-${source.recordingStatus}`}>
                            {recordingCoverageLabel(source.recordingStatus)}
                          </span>
                        </div>
                        <p>{source.remediation}</p>
                        <small className="vi-search-coverage-facts">
                          {source.semanticSegments !== null
                            ? `${source.semanticSegments.toLocaleString()} indexed semantic ${source.semanticSegments === 1 ? "moment" : "moments"}`
                            : "Semantic count unavailable"}
                          {indexedAt ? ` · latest indexed ${indexedAt}` : ""}
                          {retainedUntil ? ` · retained through ${retainedUntil}` : ""}
                        </small>
                      </article>
                    );
                  })}
                  {!searchCoverage.sources.length && (
                    <p className="vi-search-coverage-empty">
                      Video I/O reports no configured sources. Connect or ingest a
                      source, then return here to confirm its index and retention.
                    </p>
                  )}
                </div>
              </>
            ) : (
              <p className="vi-search-coverage-empty" role="status">
                {searchCoverageUnavailable
                  ? "Configured source coverage is unavailable. Check Video I/O and local search services, then refresh this view."
                  : "Reading configured sources, local semantic indexes, and retained recording windows…"}
              </p>
            )}
          </article>

          <article className="vi-system-pipeline">
            <div className="vi-system-section-heading">
              <div>
                <span className="vi-eyebrow">Active pipeline</span>
                <h2>From pixels to evidence</h2>
              </div>
              <span><IconShieldLock size={16} /> Cloud inference: not configured</span>
            </div>
            <div className="vi-pipeline-stages">
              {[
                { icon: IconVideo, label: "Video I/O", detail: "Live + recorded" },
                { icon: IconBolt, label: "Cosmos Embed", detail: "Semantic moments" },
                { icon: IconDatabase, label: "Local index", detail: "Retrieve + retain" },
                { icon: IconDeviceDesktopAnalytics, label: "Cosmos Reason", detail: "Visual grounding" },
                { icon: IconCpu, label: "Nemotron", detail: "Synthesize + explain" },
              ].map((stage, index) => {
                const Icon = stage.icon;
                return (
                  <React.Fragment key={stage.label}>
                    <div className="vi-pipeline-stage">
                      <Icon size={21} />
                      <strong>{stage.label}</strong>
                      <span>{stage.detail}</span>
                    </div>
                    {index < 4 && <i>→</i>}
                  </React.Fragment>
                );
              })}
            </div>
          </article>

          <article className="vi-service-table">
            <div className="vi-system-section-heading">
              <div>
                <span className="vi-eyebrow">Runtime readiness</span>
                <h2>Local services</h2>
              </div>
              <span>
                Last checked {health ? new Date(health.checkedAt).toLocaleTimeString() : "—"}
              </span>
            </div>
            <div className="vi-service-list">
              {(health?.services ?? []).map((service) => (
                <div key={service.key}>
                  <span className={service.ok ? "is-ready" : "is-offline"}>
                    {service.ok ? <IconCheck size={15} /> : <IconServer size={15} />}
                  </span>
                  <strong>{service.label}</strong>
                  <em>{service.ok ? "Ready" : "Unavailable"}</em>
                  <small>{service.latencyMs == null ? "—" : `${service.latencyMs} ms`}</small>
                </div>
              ))}
              {!health && <p>Reading local service health…</p>}
            </div>
          </article>
        </div>
      )}

      {panel === "sources" && <div className="vi-legacy-surface vi-system-admin">{sources}</div>}
      {panel === "rules" && <div className="vi-legacy-surface vi-system-admin">{rules}</div>}
    </section>
  );
}
