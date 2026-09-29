// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import { LiveModeNav } from "./LiveModeNav";
import { evidenceClipEndpoint } from "./evidenceClip";
import { EventReport } from "./EventReport";
import {
  consolidateIncidents,
  incidentDurationLabel,
  incidentTitle,
  incidentVerdict,
  incidentVerdictLabel,
  isOperatorIncidentCandidate,
  isDirectModelMatch,
  type AnalyticsIncident,
  type ConsolidatedIncident,
} from "./incidentModel";
import type { InvestigationRecord } from "./investigation";
import type { IncidentStateRecord, IncidentWorkflowState } from "./incidentState";
import { type MonitoringRule } from "./monitoringRules";
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
  | "model_match"
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

export function incidentRule(
  incident: AnalyticsIncident,
  rules: MonitoringRule[],
): MonitoringRule | null {
  const ruleId = incident.info?.alertRuleId;
  if (!ruleId) return null;
  // Shared source or similar wording does not establish which rule fired.
  return rules.find(rule => rule.backendRuleId === ruleId || rule.id === ruleId) ?? null;
}

function IncidentMedia({
  incident,
  onClose,
  onStateChange,
  onReportSaved,
  rule,
  sourceNames,
  workflowState,
  vstApiUrl,
}: {
  incident: ConsolidatedIncident;
  onClose: () => void;
  onStateChange: (state: IncidentWorkflowState) => void;
  onReportSaved: (record: InvestigationRecord) => void;
  rule: MonitoringRule | null;
  sourceNames: Record<string, string>;
  workflowState: IncidentWorkflowState;
  vstApiUrl?: string | null;
}) {
  const snapshot = incidentSnapshot(incident, vstApiUrl);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [evidenceSensorId, setEvidenceSensorId] = useState<string | null>(null);
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
        setEvidenceSensorId(stream.streamId);

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
                : "Footage could not be retrieved for this event interval. It may no longer be retained, or the video service may be unavailable."}
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
          <h2>{rule?.engine === "vlm" ? rule.name : incidentTitle(incident)}</h2>
          <p>
            {!isOperatorIncidentCandidate(incident)
              ? "Backend processing record retained for audit."
              : incident.info?.reasoning ||
                incident.info?.verificationResponseStatus ||
                (incident.info?.triggerPhrase ? "The visual model matched the rule condition. Review the footage before confirming what happened." : "No model reasoning was recorded for this incident.")}
          </p>
          {incident.info?.prompt && <p><strong>Recorded condition</strong><br />{incident.info.prompt}</p>}
          <dl>
            <div>
              <dt>Triggered by</dt>
              <dd>{rule?.name ?? (incident.info?.alertRuleId ? "Rule record unavailable" : "Analytics candidate")}</dd>
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
          {videoUrl && evidenceSensorId && <EventReport key={incident.Id} incident={incident} rule={rule} sensorId={evidenceSensorId} sourceName={incidentSourceName(incident, sourceNames)} onSaved={onReportSaved} />}
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
  const [investigationsError, setInvestigationsError] = useState<string | null>(null);
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({});
  const [sourceCount, setSourceCount] = useState(0);
  const [rules, setRules] = useState<MonitoringRule[]>([]);
  const [workflowStates, setWorkflowStates] = useState<Record<string, IncidentStateRecord>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ConsolidatedIncident | null>(null);
  const [activityFilter, setActivityFilter] =
    useState<ActivityFilter>("actionable");
  const [visibleInvestigations, setVisibleInvestigations] = useState(4);
  const [visibleCount, setVisibleCount] = useState(ACTIVITY_PAGE_SIZE);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setInvestigationsError(null);
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
      try {
        if (investigationResult.status === "rejected" || !investigationResult.value.ok) {
          throw new Error("Saved reports could not be refreshed.");
        }
        const saved = await investigationResult.value.json() as { investigations?: InvestigationRecord[] };
        setInvestigations(saved.investigations ?? []);
      } catch {
        setInvestigationsError("Saved reports could not be refreshed. Any shown below are from the last successful load.");
      }
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
    () => consolidatedIncidents.filter(isOperatorIncidentCandidate),
    [consolidatedIncidents]
  );

  const stats = useMemo(() => {
    const sources = new Map<string, number>();
    const verdicts = { model_match: 0, confirmed: 0, rejected: 0, failed: 0, unverified: 0 };
    operatorIncidents.forEach((incident) => {
      const source = incidentSourceName(incident, sourceNames);
      sources.set(source, (sources.get(source) ?? 0) + 1);
      verdicts[isDirectModelMatch(incident) ? "model_match" : verdictFor(incident)] += 1;
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
        if (activityFilter === "model_match") return isDirectModelMatch(incident);
        if (activityFilter === "confirmed") return verdictFor(incident) === "confirmed" && !isDirectModelMatch(incident);
        return verdictFor(incident) === activityFilter;
      }),
    [activityFilter, consolidatedIncidents, workflowStates]
  );
  const shownActivity = activityIncidents.slice(0, visibleCount);

  const maxBucket = Math.max(1, ...stats.buckets.map(([, count]) => count));
  const awaitingReview = operatorIncidents.filter(incident =>
    verdictFor(incident) !== "rejected" && incidentWorkflowState(incident, workflowStates) === "new"
  ).length;
  const featuredIncident = operatorIncidents.find(incident =>
    verdictFor(incident) !== "rejected" && incidentWorkflowState(incident, workflowStates) !== "resolved"
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

      {!loading && !error && initialMode === "insights" && !operatorIncidents.length && (
        <section className="vi-insights-start" aria-label="Insights awaiting event evidence">
          <span className="vi-eyebrow">FROM EVENTS TO OPERATIONAL INSIGHT</span>
          <h1>See patterns behind the moments</h1>
          <p>Once monitored events are captured, compare when they happen, which cameras they come from, and what verification found.</p>
          <dl>
            <div><dt>When does activity concentrate?</dt><dd>Compare event counts by hour to identify periods worth reviewing.</dd></div>
            <div><dt>Where should you look first?</dt><dd>Compare sources, then open the footage behind an event.</dd></div>
            <div><dt>Which events need a closer look?</dt><dd>Separate confirmed observations from candidates awaiting verification.</dd></div>
          </dl>
          <div className="vi-activity-empty">
            <IconActivity size={24} />
            <strong>No event evidence to summarize yet</strong>
            <p>Charts appear when incident records are available. This view does not measure camera uptime or establish that a scene is safe.</p>
            <div className="vi-activity-empty-actions">
              <button type="button" onClick={() => onModeChange("live")}>Check cameras</button>
              <button type="button" onClick={onOpenRules}>Review monitoring rules</button>
              {investigations.length > 0 && <button type="button" onClick={() => onModeChange("activity")}>View {investigations.length} saved {investigations.length === 1 ? "report" : "reports"}</button>}
            </div>
          </div>
        </section>
      )}

      {!loading && !error && initialMode === "insights" && operatorIncidents.length > 0 && (
        <div className="vi-insights">
          <div className="vi-activity-heading"><div>
            <h1>Activity at a glance</h1>
            <p>See where events happened, then open the footage behind a match.</p>
          </div></div>
          <div className="vi-operational-briefing">
            <IconSparkles size={20} />
            <strong>Event overview</strong>
            <span>
              {operatorIncidents.length} recorded {operatorIncidents.length === 1 ? "event" : "events"} from {stats.sources.length} {stats.sources.length === 1 ? "source" : "sources"}.
              {" "}{awaitingReview} awaiting review; {stats.verdicts.model_match} direct model {stats.verdicts.model_match === 1 ? "match" : "matches"}.
              {" "}Model outcomes and review status are separate. Counts do not measure accuracy.
            </span>
          </div>
          <div className="vi-insight-metrics">
            <div>
              <IconActivity size={20} />
              <strong>{operatorIncidents.length}</strong>
              <span>Recorded events</span>
            </div>
            <div>
              <IconCheck size={20} />
              <strong>{awaitingReview}</strong>
              <span>Awaiting review</span>
            </div>
            <div>
              <IconCamera size={20} />
              <strong>{sourceCount || stats.sources.length}</strong>
              <span>Configured sources</span>
            </div>
            <div>
              <IconShieldCheck size={20} />
              <strong>{investigations.length}</strong>
              <span>Saved reports</span>
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
          <div className="vi-insights-chart">
            <div className="vi-insight-heading">
              <div>
                <h2>Events over time</h2>
                <p>Loaded events by hour · latest 18 occupied hours · up to 100 source records</p>
              </div>
              <span>Recorded history</span>
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
                        month: "short", day: "numeric", hour: "numeric",
                      }).format(new Date(timestamp))}
                    </small>
                  </div>
                ))
              ) : (
                <p className="vi-insight-empty">
                  No operator events in this period. Try another activity filter
                  or explore indexed footage.
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
              <h2>Model outcomes</h2>
              {Object.entries(stats.verdicts).map(([verdict, count]) => (
                <div className="vi-breakdown-row" key={verdict}>
                  <span>
                    {
                      {
                        model_match: "Rule matched",
                        confirmed: "Verification passed",
                        rejected: "Dismissed",
                        failed: "Verification failed",
                        unverified: "Unverified",
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

        </div>
      )}

      {!loading && initialMode === "activity" && (
        <div className="vi-activity-list">
          <div className="vi-activity-heading">
            <div>
              <h1>Event review</h1>
              <p>
                Review detected events, inspect their footage, and decide what needs attention.
                Each event shows its verification and review status.
              </p>
            </div>
            <label className="vi-activity-filter">
              <span>Show</span>
              <select
                aria-label="Activity filter"
                disabled={Boolean(error)}
                value={activityFilter}
                onChange={(event) => {
                  setActivityFilter(event.target.value as ActivityFilter);
                  setVisibleCount(ACTIVITY_PAGE_SIZE);
                }}
              >
                <option value="actionable">Needs attention</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
                <option value="model_match">Model match</option>
                <option value="confirmed">Verification passed</option>
                <option value="unverified">Unverified</option>
                <option value="failed">Verification failed</option>
                <option value="rejected">Rejected</option>
                <option value="all">All, including diagnostics</option>
              </select>
            </label>
            <span>
              {error ? "Event data unavailable" : `${activityIncidents.length} ${activityIncidents.length === 1 ? "incident" : "incidents"}`}
            </span>
          </div>
          {investigationsError && <p role="status" className="vi-investigate-error">{investigationsError}</p>}
          {investigations.length > 0 && (
            <section
              className="vi-saved-investigations"
              aria-label="Saved reports"
            >
              <header>
                <div>
                  <IconShieldCheck size={18} />
                  <span>
                    <strong>Saved reports</strong>
                    <small>
                      Answers, notes and video references saved on this device
                    </small>
                  </span>
                </div>
                <span>{investigations.length}</span>
              </header>
              <div>
                {investigations.slice(0, visibleInvestigations).map((investigation) => (
                  <article key={investigation.id}>
                    <span className={`is-${investigation.severity}`}>
                      {investigation.severity}
                    </span>
                    <div>
                      <strong>{investigation.title}</strong>
                      <small>
                        {investigation.evidence.length}{" "}
                        {investigation.evidence.length === 1
                          ? "video reference"
                          : "video references"}
                        {investigation.evidence.some(
                          (item) => item.media_status === "retained"
                        )
                          ? ` · ${
                              investigation.evidence.filter(
                                (item) => item.media_status === "retained"
                              ).length
                            } retained locally`
                          : " · video depends on source availability"}{" "}
                        · {investigation.disposition.replaceAll("_", " ")} ·{" "}
                        {formatIncidentTime(investigation.created_at)}
                      </small>
                    </div>
                    <a
                      href={investigation.report_url}
                    >
                      <IconFileReport size={15} /> Open report
                    </a>
                  </article>
                ))}
              </div>
              {investigations.length > visibleInvestigations && (
                <footer className="vi-activity-more">
                  <button type="button" onClick={() => setVisibleInvestigations(count => count + 8)}>Show older reports</button>
                  <span>Showing {Math.min(visibleInvestigations, investigations.length)} of {investigations.length}</span>
                </footer>
              )}
            </section>
          )}
          {!error && (shownActivity.length ? (
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
              <IconActivity size={24} />
              <strong>{consolidatedIncidents.length ? "No events match this filter" : "No detected events yet"}</strong>
              <p>{consolidatedIncidents.length
                ? "Other review states or diagnostic records may be available."
                : "When a monitored condition is detected, review its footage and verification here. An empty event list does not confirm that cameras are connected or monitoring is active."}</p>
              <div className="vi-activity-empty-actions">
                {consolidatedIncidents.length ? (
                  <button type="button" onClick={() => { setActivityFilter("all"); setVisibleCount(ACTIVITY_PAGE_SIZE); }}>Show all records</button>
                ) : (
                  <>
                    <button type="button" onClick={() => onModeChange("live")}>Check cameras</button>
                    <button type="button" onClick={onOpenRules}>Review monitoring rules</button>
                  </>
                )}
              </div>
            </div>
          ))}
          {!error && activityIncidents.length > shownActivity.length && (
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
          onReportSaved={(record) => setInvestigations((current) => [record, ...current.filter((item) => item.id !== record.id)])}
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
  const start = Date.parse(incident.timestamp);
  const end = Date.parse(incident.end ?? "");
  const canFindFootage = Boolean(vstApiUrl && incident.sensorId && Number.isFinite(start) && Number.isFinite(end) && end > start);
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
        <h2>{rule?.engine === "vlm" ? rule.name : incidentTitle(incident)}</h2>
        <p>
          {!isOperatorIncidentCandidate(incident)
            ? "Backend processing record retained for audit."
            : incident.info?.reasoning ||
              incident.info?.verificationResponseStatus ||
              (incident.info?.triggerPhrase ? "The visual model matched the rule condition. Review the footage." : "Visual observation retained for review.")}
        </p>
        <time>
          <IconClock size={14} /> {formatIncidentTime(incident.timestamp)} ·{" "}
          {incidentDurationLabel(incident)} ·{" "}
          {incidentSourceName(incident, sourceNames)}
        </time>
        <div className="vi-incident-rule-line"><IconShieldCheck size={14} /> {rule ? `Triggered by ${rule.name}` : incident.info?.alertRuleId ? "Rule record unavailable" : "Analytics candidate"}<span className={`is-${workflowState}`}>{workflowState}</span></div>
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
        disabled={!hasRetainedMedia && !canFindFootage}
        title={
          hasRetainedMedia
            ? "Open retained incident evidence"
            : canFindFootage ? "Look for recorded footage at this event's source and time" : "This record has no attached media or usable source interval"
        }
      >
        {hasRetainedMedia ? (
          <>
            <IconPlayerPlay size={17} /> Open evidence
          </>
        ) : canFindFootage ? (
          <><IconPlayerPlay size={17} /> Find footage</>
        ) : (
          <>
            <IconClock size={17} /> Timing only
          </>
        )}
      </button>
    </article>
  );
}
