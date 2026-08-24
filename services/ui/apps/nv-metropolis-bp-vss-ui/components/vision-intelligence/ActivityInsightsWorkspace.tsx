// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import { LiveModeNav } from "./LiveModeNav";
import { evidenceClipEndpoint } from "./evidenceClip";
import {
  consolidateIncidents,
  incidentDurationLabel,
  incidentTitle,
  incidentVerdict,
  incidentVerdictLabel,
  isOperatorIncidentCandidate,
  isOperatorRelevantIncident,
  type AnalyticsIncident,
  type ConsolidatedIncident,
} from "./incidentModel";
import type { InvestigationRecord } from "./investigation";
import type { IncidentStateRecord, IncidentWorkflowState } from "./incidentState";
import { ruleMatchesSource, type MonitoringRule } from "./monitoringRules";
import { streamDisplayName } from "./utils";
import {
  IconActivity,
  IconAlertTriangle,
  IconCamera,
  IconCheck,
  IconClock,
  IconFileReport,
  IconPlayerPlay,
  IconRefresh,
  IconShieldCheck,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";

type AnalyticsMode = "activity" | "insights";
type ActivityFilter =
  | "actionable"
  | "acknowledged"
  | "all"
  | "confirmed"
  | "failed"
  | "rejected"
  | "resolved"
  | "unverified";

const ACTIVITY_PAGE_SIZE = 6;

interface ActivityInsightsWorkspaceProps {
  initialMode: AnalyticsMode;
  onModeChange: (mode: "live" | AnalyticsMode) => void;
  onOpenRules: () => void;
  vstApiUrl?: string | null;
}

function verdictFor(
  incident: AnalyticsIncident
): "confirmed" | "rejected" | "failed" | "unverified" {
  return incidentVerdict(incident);
}

function formatIncidentTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function normalizeAnalyticsUrl(
  value: string,
  vstApiUrl?: string | null
): string {
  if (!value || !vstApiUrl) return value;
  try {
    const target = new URL(value);
    const origin = new URL(vstApiUrl).origin;
    return `${origin}${target.pathname}${target.search}`;
  } catch {
    return value;
  }
}

function incidentSnapshot(
  incident: AnalyticsIncident,
  vstApiUrl?: string | null
): string | null {
  const raw = incident.info?.snapshotUrls;
  if (!raw) return null;
  try {
    const values = JSON.parse(raw) as string[];
    return values[0] ? normalizeAnalyticsUrl(values[0], vstApiUrl) : null;
  } catch {
    return null;
  }
}

function incidentSourceName(
  incident: AnalyticsIncident,
  sourceNames: Record<string, string> = {}
): string {
  const sourceId = incident.sensorId || "Unknown source";
  return sourceNames[sourceId] || streamDisplayName(sourceId);
}

function incidentWorkflowState(
  incident: AnalyticsIncident,
  states: Record<string, IncidentStateRecord>,
): IncidentWorkflowState {
  return states[incident.Id]?.state ?? "new";
}

function incidentRule(
  incident: AnalyticsIncident,
  rules: MonitoringRule[],
): MonitoringRule | null {
  const candidates = rules.filter((rule) => ruleMatchesSource(rule, incident.sensorId));
  if (candidates.length === 1) return candidates[0];
  const description = `${incident.info?.alertCategory ?? ""} ${incident.info?.description ?? ""} ${incident.info?.reasoning ?? ""}`;
  const kind = /proximity|too close|near/i.test(description) ? "proximity"
    : /restricted|zone|area|entered/i.test(description) ? "area-entry"
    : /visual|semantic/i.test(description) ? "semantic" : null;
  return candidates.find((rule) => rule.kind === kind) ?? null;
}

function IncidentMedia({
  incident,
  onClose,
  onStateChange,
  rule,
  sourceNames,
  workflowState,
  vstApiUrl,
}: {
  incident: ConsolidatedIncident;
  onClose: () => void;
  onStateChange: (state: IncidentWorkflowState) => void;
  rule: MonitoringRule | null;
  sourceNames: Record<string, string>;
  workflowState: IncidentWorkflowState;
  vstApiUrl?: string | null;
}) {
  const snapshot = incidentSnapshot(incident, vstApiUrl);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [clipStatus, setClipStatus] = useState<
    "loading" | "ready" | "snapshot"
  >("loading");

  const dialogRef = useDialogAccessibility<HTMLDivElement>({ isOpen: true, onClose });

  useEffect(() => {
    const incidentEnd = incident.end;
    if (!vstApiUrl || !incident.sensorId || !incidentEnd) {
      setClipStatus("snapshot");
      return;
    }

    const controller = new AbortController();
    const prepareClip = async () => {
      try {
        const streamsResponse = await fetch(`${vstApiUrl}/v1/live/streams`, {
          signal: controller.signal,
        });
        if (!streamsResponse.ok)
          throw new Error("Source catalog is unavailable.");
        const catalog = (await streamsResponse.json()) as Array<
          Record<string, Array<{ name?: string; streamId?: string }>>
        >;
        const streams = catalog.flatMap((sensor) =>
          Object.values(sensor).flat()
        );
        const stream = streams.find(
          (candidate) =>
            candidate.streamId === incident.sensorId ||
            candidate.name === incident.sensorId
        );
        if (!stream?.streamId)
          throw new Error("The source is no longer in the catalog.");

        const clipResponse = await fetch(
          evidenceClipEndpoint(
            stream.streamId,
            incident.timestamp,
            incidentEnd
          ),
          { signal: controller.signal }
        );
        if (!clipResponse.ok)
          throw new Error("The evidence clip could not be prepared.");
        const data = (await clipResponse.json()) as { videoUrl?: string };
        if (!data.videoUrl)
          throw new Error("The evidence clip URL was not returned.");
        setVideoUrl(normalizeAnalyticsUrl(data.videoUrl, vstApiUrl));
        setClipStatus("ready");
      } catch (error) {
        if (!controller.signal.aborted) setClipStatus("snapshot");
      }
    };
    void prepareClip();
    return () => controller.abort();
  }, [incident.end, incident.sensorId, incident.timestamp, vstApiUrl]);

  return (
    <div
      ref={dialogRef}
      className="vi-evidence-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Incident evidence"
    >
      <div className="vi-incident-viewer">
        <button
          className="vi-evidence-close"
          type="button"
          onClick={onClose}
          aria-label="Close incident"
        >
          <IconX size={21} />
        </button>
        <div className="vi-incident-media">
          {videoUrl ? (
            <video
              src={videoUrl}
              poster={snapshot ?? undefined}
              controls
              autoPlay
              playsInline
              onError={() => {
                setVideoUrl(null);
                setClipStatus("snapshot");
              }}
            />
          ) : snapshot ? (
            <img src={snapshot} alt="Incident evidence" />
          ) : (
            <div>
              {clipStatus === "loading"
                ? "Preparing evidence…"
                : "No media was attached to this incident."}
            </div>
          )}
          {clipStatus === "loading" && snapshot && (
            <span className="vi-evidence-media-note">
              Preparing recorded clip…
            </span>
          )}
          {clipStatus === "snapshot" && snapshot && (
            <span className="vi-evidence-media-note">Recorded frame</span>
          )}
        </div>
        <div className="vi-incident-copy">
          <span className={`vi-verdict vi-verdict--${verdictFor(incident)}`}>
            {incidentVerdictLabel(incident)}
          </span>
          <h2>{incidentTitle(incident)}</h2>
          <p>
            {!isOperatorIncidentCandidate(incident)
              ? "Backend processing record retained for audit."
              : incident.info?.reasoning ||
                incident.info?.verificationResponseStatus ||
                "No model reasoning was recorded for this incident."}
          </p>
          <dl>
            <div>
              <dt>Triggered by</dt>
              <dd>{rule?.name ?? "Analytics candidate"}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{incidentSourceName(incident, sourceNames)}</dd>
            </div>
            <div>
              <dt>Observed</dt>
              <dd>{formatIncidentTime(incident.timestamp)}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{incidentDurationLabel(incident)}</dd>
            </div>
            <div>
              <dt>Candidate records</dt>
              <dd>{incident.candidateCount}</dd>
            </div>
          </dl>
          <div className="vi-incident-workflow">
            <span>Review state: <strong>{workflowState}</strong></span>
            {workflowState === "new" && <button type="button" onClick={() => onStateChange("acknowledged")}>Acknowledge</button>}
            {workflowState !== "resolved" && <button className="is-primary" type="button" onClick={() => onStateChange("resolved")}>Resolve incident</button>}
            {workflowState === "resolved" && <button type="button" onClick={() => onStateChange("new")}>Reopen</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ActivityInsightsWorkspace({
  initialMode,
  onModeChange,
  onOpenRules,
  vstApiUrl,
}: ActivityInsightsWorkspaceProps) {
  const [incidents, setIncidents] = useState<AnalyticsIncident[]>([]);
  const [investigations, setInvestigations] = useState<InvestigationRecord[]>(
    []
  );
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({});
  const [sourceCount, setSourceCount] = useState(0);
  const [rules, setRules] = useState<MonitoringRule[]>([]);
  const [workflowStates, setWorkflowStates] = useState<Record<string, IncidentStateRecord>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ConsolidatedIncident | null>(null);
  const [activityFilter, setActivityFilter] =
    useState<ActivityFilter>("actionable");
  const [visibleCount, setVisibleCount] = useState(ACTIVITY_PAGE_SIZE);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [incidentResult, investigationResult, sourceResult, rulesResult, stateResult] =
        await Promise.allSettled([
          fetch("/api/vision/incidents"),
          fetch("/api/vision/investigations"),
          vstApiUrl
            ? fetch(`${vstApiUrl}/v1/live/streams`)
            : Promise.resolve(null),
          fetch("/api/vision/monitoring-rules", { cache: "no-store" }),
          fetch("/api/vision/incident-state", { cache: "no-store" }),
        ]);
      if (incidentResult.status === "rejected") throw incidentResult.reason;
      const data = (await incidentResult.value.json()) as {
        incidents?: AnalyticsIncident[];
        error?: string;
      };
      if (!incidentResult.value.ok)
        throw new Error(
          data.error || `Analytics returned ${incidentResult.value.status}.`
        );
      setIncidents(data.incidents ?? []);
      if (
        investigationResult.status === "fulfilled" &&
        investigationResult.value.ok
      ) {
        const saved = (await investigationResult.value.json()) as {
          investigations?: InvestigationRecord[];
        };
        setInvestigations(saved.investigations ?? []);
      } else {
        setInvestigations([]);
      }
      if (sourceResult.status === "fulfilled" && sourceResult.value?.ok) {
        const catalog = (await sourceResult.value.json()) as unknown;
        if (Array.isArray(catalog)) {
          const names: Record<string, string> = {};
          for (const sensor of catalog) {
            if (!sensor || typeof sensor !== "object") continue;
            for (const [sensorId, streams] of Object.entries(sensor)) {
              if (!Array.isArray(streams)) continue;
              for (const stream of streams) {
                if (!stream || typeof stream !== "object") continue;
                const candidate = stream as {
                  name?: string;
                  streamId?: string;
                };
                const displayName = streamDisplayName(
                  candidate.name || sensorId
                );
                names[sensorId] = displayName;
                if (candidate.name) names[candidate.name] = displayName;
                if (candidate.streamId) names[candidate.streamId] = displayName;
              }
            }
          }
          setSourceNames(names);
          setSourceCount(new Set(Object.values(names)).size);
        }
      } else {
        setSourceCount(0);
      }
      if (rulesResult.status === "fulfilled" && rulesResult.value.ok) {
        const value = await rulesResult.value.json() as { rules?: MonitoringRule[] };
        setRules(value.rules ?? []);
      } else setRules([]);
      if (stateResult.status === "fulfilled" && stateResult.value.ok) {
        const value = await stateResult.value.json() as { states?: Record<string, IncidentStateRecord> };
        setWorkflowStates(value.states ?? {});
      } else setWorkflowStates({});
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Analytics are unavailable."
      );
    } finally {
      setLoading(false);
    }
  }, [vstApiUrl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const consolidatedIncidents = useMemo(
    () => consolidateIncidents(incidents),
    [incidents]
  );
  const operatorIncidents = useMemo(
    () => consolidatedIncidents.filter(isOperatorRelevantIncident),
    [consolidatedIncidents]
  );

  const stats = useMemo(() => {
    const sources = new Map<string, number>();
    const verdicts = { confirmed: 0, rejected: 0, failed: 0, unverified: 0 };
    operatorIncidents.forEach((incident) => {
      const source = incidentSourceName(incident, sourceNames);
      sources.set(source, (sources.get(source) ?? 0) + 1);
      verdicts[verdictFor(incident)] += 1;
    });
    const buckets = new Map<number, number>();
    operatorIncidents.forEach((incident) => {
      const date = new Date(incident.timestamp);
      if (Number.isNaN(date.getTime())) return;
      date.setMinutes(0, 0, 0);
      const key = date.getTime();
      buckets.set(key, (buckets.get(key) ?? 0) + 1);
    });
    return {
      sources: [...sources.entries()].sort((a, b) => b[1] - a[1]),
      verdicts,
      buckets: [...buckets.entries()]
        .sort(([left], [right]) => left - right)
        .slice(-18),
    };
  }, [operatorIncidents, sourceNames]);

  const activityIncidents = useMemo(
    () =>
      consolidatedIncidents.filter((incident) => {
        if (activityFilter === "all") return true;
        if (!isOperatorIncidentCandidate(incident)) return false;
        if (activityFilter === "actionable")
          return verdictFor(incident) !== "rejected" && incidentWorkflowState(incident, workflowStates) === "new";
        if (activityFilter === "acknowledged" || activityFilter === "resolved")
          return incidentWorkflowState(incident, workflowStates) === activityFilter;
        return verdictFor(incident) === activityFilter;
      }),
    [activityFilter, consolidatedIncidents, workflowStates]
  );
  const shownActivity = activityIncidents.slice(0, visibleCount);

  const maxBucket = Math.max(1, ...stats.buckets.map(([, count]) => count));
  const confirmedPercent = operatorIncidents.length
    ? Math.round((stats.verdicts.confirmed / operatorIncidents.length) * 100)
    : 0;
  const featuredIncident = operatorIncidents.find((incident) =>
    incidentWorkflowState(incident, workflowStates) !== "resolved" && Boolean(incidentSnapshot(incident, vstApiUrl) || incident.info?.videoSource)
  );

  const setIncidentState = async (incident: ConsolidatedIncident, state: IncidentWorkflowState) => {
    const response = await fetch("/api/vision/incident-state", {
      body: JSON.stringify({ incidentId: incident.Id, state }),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    });
    const payload = await response.json() as { error?: string; record?: IncidentStateRecord };
    if (!response.ok || !payload.record) throw new Error(payload.error || "The incident state could not be saved.");
    setWorkflowStates((current) => ({ ...current, [incident.Id]: payload.record! }));
  };

  return (
    <section className="vi-analytics-workspace">
      <LiveModeNav
        active={initialMode}
        action={
          <button
            className="vi-refresh-analytics"
            type="button"
            onClick={() => void refresh()}
          >
            <IconRefresh size={16} /> Refresh
          </button>
        }
        onSelect={(mode) => mode === "rules" ? onOpenRules() : onModeChange(mode === "monitor" ? "live" : mode)}
      />

      {loading && (
        <div className="vi-investigate-loading">
          <span className="vi-spinner" /> Loading local analytics…
        </div>
      )}
      {error && (
        <div className="vi-investigate-error">
          <IconAlertTriangle size={20} /> {error}
        </div>
      )}

      {!loading && !error && initialMode === "insights" && (
        <div className="vi-insights">
          <div className="vi-operational-briefing">
            <IconSparkles size={20} />
            <strong>Operational Briefing</strong>
            <span>
              {operatorIncidents.length} operator-relevant{" "}
              {operatorIncidents.length === 1 ? "incident" : "incidents"} across{" "}
              {sourceCount || stats.sources.length}{" "}
              {(sourceCount || stats.sources.length) === 1
                ? "monitored source"
                : "monitored sources"}
              . {stats.verdicts.confirmed} confirmed;{" "}
              {stats.verdicts.failed + stats.verdicts.unverified} require
              verification. {investigations.length} saved{" "}
              {investigations.length === 1 ? "investigation" : "investigations"}
              .
            </span>
          </div>
          <div className="vi-insight-metrics">
            <div>
              <IconActivity size={20} />
              <strong>{operatorIncidents.length}</strong>
              <span>Operator incidents</span>
            </div>
            <div>
              <IconCheck size={20} />
              <strong>{stats.verdicts.confirmed}</strong>
              <span>Confirmed</span>
            </div>
            <div>
              <IconCamera size={20} />
              <strong>{sourceCount || stats.sources.length}</strong>
              <span>Monitored sources</span>
            </div>
            <div>
              <IconShieldCheck size={20} />
              <strong>{investigations.length}</strong>
              <span>Saved investigations</span>
            </div>
          </div>
          <div className="vi-insights-chart">
            <div className="vi-insight-heading">
              <div>
                <h2>Events over time</h2>
                <p>Recent incident distribution by hour</p>
              </div>
              <span>{confirmedPercent}% confirmed</span>
            </div>
            <div className="vi-bars">
              {stats.buckets.length ? (
                stats.buckets.map(([timestamp, count]) => (
                  <div className="vi-bar-column" key={timestamp}>
                    <div
                      style={{
                        height: `${Math.max(7, (count / maxBucket) * 100)}%`,
                      }}
                    >
                      <span>{count}</span>
                    </div>
                    <small>
                      {new Intl.DateTimeFormat(undefined, {
                        hour: "numeric",
                      }).format(new Date(timestamp))}
                    </small>
                  </div>
                ))
              ) : (
                <p className="vi-insight-empty">
                  No operator events in this period. Live indexing and visual
                  search remain active.
                </p>
              )}
            </div>
          </div>
          <div className="vi-insight-breakdown">
            <div>
              <h2>Where activity occurred</h2>
              {stats.sources.slice(0, 5).map(([source, count]) => (
                <div className="vi-breakdown-row" key={source}>
                  <span>{source}</span>
                  <i>
                    <b
                      style={{
                        width: `${
                          (count / Math.max(1, stats.sources[0]?.[1] ?? 1)) *
                          100
                        }%`,
                      }}
                    />
                  </i>
                  <strong>{count}</strong>
                </div>
              ))}
              {!stats.sources.length && (
                <p className="vi-insight-empty">
                  No operator-ready events have been assigned to a source yet.
                </p>
              )}
            </div>
            <div>
              <h2>Verification outcomes</h2>
              {Object.entries(stats.verdicts).map(([verdict, count]) => (
                <div className="vi-breakdown-row" key={verdict}>
                  <span>
                    {
                      {
                        confirmed: "Confirmed",
                        rejected: "Dismissed",
                        failed: "Needs review",
                        unverified: "Pending review",
                      }[verdict]
                    }
                  </span>
                  <i>
                    <b
                      className={`is-${verdict}`}
                      style={{
                        width: `${
                          operatorIncidents.length
                            ? (count / operatorIncidents.length) * 100
                            : 0
                        }%`,
                      }}
                    />
                  </i>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          </div>
          {featuredIncident && (
            <IncidentRow
              incident={featuredIncident}
              onOpen={() => setSelected(featuredIncident)}
              rule={incidentRule(featuredIncident, rules)}
              sourceNames={sourceNames}
              vstApiUrl={vstApiUrl}
              workflowState={incidentWorkflowState(featuredIncident, workflowStates)}
              featured
            />
          )}
        </div>
      )}

      {!loading && !error && initialMode === "activity" && (
        <div className="vi-activity-list">
          <div className="vi-activity-heading">
            <div>
              <h1>Activity</h1>
              <p>
                Consolidated visual incidents verified by local analytics.
                Diagnostics, dismissed candidates, and empty backend records are
                hidden by default.
              </p>
            </div>
            <label className="vi-activity-filter">
              <span>Show</span>
              <select
                aria-label="Activity filter"
                value={activityFilter}
                onChange={(event) => {
                  setActivityFilter(event.target.value as ActivityFilter);
                  setVisibleCount(ACTIVITY_PAGE_SIZE);
                }}
              >
                <option value="actionable">Needs attention</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
                <option value="confirmed">Confirmed</option>
                <option value="unverified">Unverified</option>
                <option value="failed">Verification failed</option>
                <option value="rejected">Rejected</option>
                <option value="all">All, including diagnostics</option>
              </select>
            </label>
            <span>
              {activityIncidents.length}{" "}
              {activityIncidents.length === 1 ? "incident" : "incidents"}
            </span>
          </div>
          {investigations.length > 0 && (
            <section
              className="vi-saved-investigations"
              aria-label="Saved investigations"
            >
              <header>
                <div>
                  <IconShieldCheck size={18} />
                  <span>
                    <strong>Saved investigations</strong>
                    <small>
                      Operator-created evidence briefings retained locally on
                      Thor
                    </small>
                  </span>
                </div>
                <span>{investigations.length}</span>
              </header>
              <div>
                {investigations.slice(0, 4).map((investigation) => (
                  <article key={investigation.id}>
                    <span className={`is-${investigation.severity}`}>
                      {investigation.severity}
                    </span>
                    <div>
                      <strong>{investigation.title}</strong>
                      <small>
                        {investigation.evidence.length}{" "}
                        {investigation.evidence.length === 1
                          ? "citation"
                          : "citations"}
                        {investigation.evidence.some(
                          (item) => item.media_status === "retained"
                        )
                          ? ` · ${
                              investigation.evidence.filter(
                                (item) => item.media_status === "retained"
                              ).length
                            } retained locally`
                          : " · source retention"}{" "}
                        · {investigation.disposition.replaceAll("_", " ")} ·{" "}
                        {formatIncidentTime(investigation.created_at)}
                      </small>
                    </div>
                    <a
                      href={investigation.report_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <IconFileReport size={15} /> Open report
                    </a>
                  </article>
                ))}
              </div>
            </section>
          )}
          {shownActivity.length ? (
            shownActivity.map((incident) => (
              <IncidentRow
                key={incident.Id}
                incident={incident}
                onOpen={() => setSelected(incident)}
                rule={incidentRule(incident, rules)}
                sourceNames={sourceNames}
                vstApiUrl={vstApiUrl}
                workflowState={incidentWorkflowState(incident, workflowStates)}
              />
            ))
          ) : (
            <div className="vi-activity-empty">
              <IconCheck size={24} />
              <strong>No activity in this view</strong>
              <span>Choose another filter or refresh local analytics.</span>
            </div>
          )}
          {activityIncidents.length > shownActivity.length && (
            <div className="vi-activity-more">
              <button
                type="button"
                onClick={() =>
                  setVisibleCount((count) => count + ACTIVITY_PAGE_SIZE)
                }
              >
                Load more activity
              </button>
              <span>
                Showing {shownActivity.length} of {activityIncidents.length}
              </span>
            </div>
          )}
        </div>
      )}

      {selected && (
        <IncidentMedia
          incident={selected}
          onClose={() => setSelected(null)}
          onStateChange={(state) => void setIncidentState(selected, state).catch((requestError) => setError(requestError instanceof Error ? requestError.message : "The incident could not be updated."))}
          rule={incidentRule(selected, rules)}
          sourceNames={sourceNames}
          vstApiUrl={vstApiUrl}
          workflowState={incidentWorkflowState(selected, workflowStates)}
        />
      )}
    </section>
  );
}

function IncidentRow({
  incident,
  onOpen,
  rule,
  sourceNames,
  vstApiUrl,
  workflowState,
  featured = false,
}: {
  incident: ConsolidatedIncident;
  onOpen: () => void;
  rule: MonitoringRule | null;
  sourceNames: Record<string, string>;
  vstApiUrl?: string | null;
  workflowState: IncidentWorkflowState;
  featured?: boolean;
}) {
  const snapshot = incidentSnapshot(incident, vstApiUrl);
  const hasRetainedMedia = Boolean(snapshot || incident.info?.videoSource);
  return (
    <article
      className={featured ? "vi-incident-row is-featured" : "vi-incident-row"}
    >
      <div className="vi-incident-thumb">
        {snapshot ? <img src={snapshot} alt="" /> : <IconCamera size={25} />}
      </div>
      <div className="vi-incident-row-copy">
        <span className={`vi-verdict vi-verdict--${verdictFor(incident)}`}>
          {incidentVerdictLabel(incident)}
        </span>
        <h2>{incidentTitle(incident)}</h2>
        <p>
          {!isOperatorIncidentCandidate(incident)
            ? "Backend processing record retained for audit."
            : incident.info?.reasoning ||
              incident.info?.verificationResponseStatus ||
              "Visual observation retained for review."}
        </p>
        <time>
          <IconClock size={14} /> {formatIncidentTime(incident.timestamp)} ·{" "}
          {incidentDurationLabel(incident)} ·{" "}
          {incidentSourceName(incident, sourceNames)}
        </time>
        <div className="vi-incident-rule-line"><IconShieldCheck size={14} /> {rule ? `Triggered by ${rule.name}` : "Analytics candidate"}<span className={`is-${workflowState}`}>{workflowState}</span></div>
        {incident.candidateCount > 1 && (
          <small>
            {incident.candidateCount} matching records consolidated · audit
            retained
          </small>
        )}
      </div>
      <button
        type="button"
        onClick={onOpen}
        disabled={!hasRetainedMedia}
        title={
          hasRetainedMedia
            ? "Open retained incident evidence"
            : "This analytics record did not retain playable media"
        }
      >
        {hasRetainedMedia ? (
          <>
            <IconPlayerPlay size={17} /> Open evidence
          </>
        ) : (
          <>
            <IconClock size={17} /> Timing only
          </>
        )}
      </button>
    </article>
  );
}
