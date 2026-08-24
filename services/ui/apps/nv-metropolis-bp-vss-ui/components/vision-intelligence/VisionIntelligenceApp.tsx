// SPDX-License-Identifier: MIT

import type { MonitoringRule } from "./monitoringRules";
import type { SystemPanel } from "./SystemWorkspace";
import { formatMemory, healthLabel, type SystemHealth } from "./systemHealth";
import type { PrimarySection, VisionStream } from "./types";
import {
  IconBell,
  IconBellCog,
  IconBulb,
  IconCpu,
  IconDotsVertical,
  IconDeviceDesktop,
  IconHome,
  IconMaximize,
  IconMoon,
  IconSearch,
  IconSun,
  IconVideo,
  IconX,
} from "@tabler/icons-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/router";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { parseWorkspace, workspaceHref } from "../../utils/workspaceRoute";
import type {
  WorkloadAdmissionFacts,
  WorkloadAdmissions,
} from "../../server/vision/workloadAdmission";
import type { SearchCoverageSnapshot } from "../../server/vision/searchCoverage";

const workspaceLoading = (workspace: string) => () => (
  <div className="vi-workspace-loading" role="status" aria-live="polite">
    <span className="vi-spinner" /> Loading {workspace}…
  </div>
);

const HomeWorkspace = dynamic(
  () => import("./HomeWorkspace").then((module) => module.HomeWorkspace),
  { loading: workspaceLoading("Home") }
);
const OperationsWorkspace = dynamic(
  () => import("./OperationsWorkspace").then((module) => module.OperationsWorkspace),
  { loading: workspaceLoading("Live") }
);
const InvestigateWorkspace = dynamic(
  () => import("./InvestigateWorkspace").then((module) => module.InvestigateWorkspace),
  { loading: workspaceLoading("Explore") }
);
const ActivityInsightsWorkspace = dynamic(
  () => import("./ActivityInsightsWorkspace").then((module) => module.ActivityInsightsWorkspace),
  { loading: workspaceLoading("Events") }
);
const CapabilitiesWorkspace = dynamic(
  () => import("./CapabilitiesWorkspace").then((module) => module.CapabilitiesWorkspace),
  { loading: workspaceLoading("Capabilities") }
);
const AlertRulesWorkspace = dynamic(
  () => import("./AlertRulesWorkspace").then((module) => module.AlertRulesWorkspace),
  { loading: workspaceLoading("Monitoring") }
);
const MonitoringRuleWizard = dynamic(
  () => import("./AlertRulesWorkspace").then((module) => module.MonitoringRuleWizard),
  { loading: workspaceLoading("Monitoring setup") }
);
const SystemWorkspace = dynamic(
  () => import("./SystemWorkspace").then((module) => module.SystemWorkspace),
  { loading: workspaceLoading("System") }
);

const VideoManagement = dynamic(
  () =>
    import("@nv-metropolis-bp-vss-ui/all").then(
      (module) => module.VideoManagementComponent
    ),
  {
    ssr: false,
    loading: () => (
      <div className="vi-system-admin-loading">
        <span>
          <i className="vi-spinner" /> Loading connected sources…
        </span>
      </div>
    ),
  }
);

interface VisionIntelligenceAppProps {
  alertsData?: any;
  searchData?: any;
  serverRenderTime?: string;
  videoManagementData?: any;
}

interface InvestigationRequest {
  camera?: VisionStream;
  query: string;
}

interface LiveTarget {
  focused: boolean;
  panel?: "history";
  streamId?: string;
}

interface PendingMonitoringSetup {
  analysisProfileId: string;
  blocking: boolean;
  complete: (result?: { analysisProfileId?: string; detectionEnabled?: boolean; ruleCreated?: boolean }) => void;
  detectionEnabled?: boolean;
  name: string;
  sensorId: string;
  sourceKind: "live" | "recorded";
  streamUrl?: string;
}

interface WorkloadAdmissionSnapshot {
  admissions: WorkloadAdmissions;
  checkedAt: string;
  qualifications: WorkloadAdmissionFacts["qualifications"];
  telemetry: WorkloadAdmissionFacts["telemetry"];
  vlm: WorkloadAdmissionFacts["vlm"];
}

type ThemePreference = "dark" | "light" | "system";

const THEME_STORAGE_KEY = "ctai-vision-theme-v1";

const sectionMeta: Record<PrimarySection, { eyebrow: string; title: string }> =
  {
    capabilities: { eyebrow: "Real demos", title: "Capabilities" },
    events: { eyebrow: "Evidence-led review", title: "Events" },
    explore: { eyebrow: "Natural-language retrieval", title: "Explore" },
    home: { eyebrow: "AI-monitored environment", title: "Home" },
    live: { eyebrow: "Connected sources", title: "Live" },
    monitoring: { eyebrow: "Rules that create incidents", title: "Monitoring" },
    system: { eyebrow: "On-device runtime", title: "System" },
  };

export default function VisionIntelligenceApp({
  alertsData,
  searchData,
  serverRenderTime,
  videoManagementData,
}: VisionIntelligenceAppProps) {
  const router = useRouter();
  const [section, setSection] = useState<PrimarySection>(() =>
    parseWorkspace(router.query.workspace)
  );
  const [eventsMode, setEventsMode] = useState<"activity" | "insights">(
    "activity"
  );
  const [investigation, setInvestigation] =
    useState<InvestigationRequest | null>(null);
  const [liveTarget, setLiveTarget] = useState<LiveTarget>({ focused: false });
  const [liveSession, setLiveSession] = useState(0);
  const [monitoringSourceId, setMonitoringSourceId] = useState<string | null>(null);
  const [pendingMonitoringSetup, setPendingMonitoringSetup] = useState<PendingMonitoringSetup | null>(null);
  const [presentationMode, setPresentationMode] = useState(false);
  const [systemPanel, setSystemPanel] = useState<SystemPanel>("overview");
  const [showSystemHealth, setShowSystemHealth] = useState(false);
  const [showThemeMenu, setShowThemeMenu] = useState(false);
  const [systemPrefersDark, setSystemPrefersDark] = useState(false);
  const [themePreference, setThemePreference] =
    useState<ThemePreference>("system");
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null);
  const [workloadAdmission, setWorkloadAdmission] =
    useState<WorkloadAdmissionSnapshot | null>(null);
  const [searchCoverage, setSearchCoverage] =
    useState<SearchCoverageSnapshot | null>(null);
  const [searchCoverageUnavailable, setSearchCoverageUnavailable] =
    useState(false);
  const vstApiUrl =
    videoManagementData?.vstApiUrl ??
    searchData?.vstApiUrl ??
    alertsData?.vstApiUrl;
  const localProcessingStatus = systemHealth?.status ?? "offline";
  const visualAnalystAvailable = systemHealth
    ? ["agent", "vlm"].every(
        (key) =>
          systemHealth.services.find((service) => service.key === key)?.ok
      )
    : null;
  const acceleratorActive = systemHealth
    ? ["perception", "embedding", "vlm", "llm"].some(
        (key) =>
          systemHealth.services.find((service) => service.key === key)?.ok
      )
    : false;
  const resolvedTheme =
    themePreference === "system"
      ? systemPrefersDark
        ? "dark"
        : "light"
      : themePreference;
  const interactiveAdmission =
    workloadAdmission?.admissions.current_visual_question;

  const navigateToSection = useCallback(
    (nextSection: PrimarySection) => {
      setSection(nextSection);
      if (!router.isReady) return;

      void router.push(workspaceHref(nextSection, router.query), undefined, {
        shallow: true,
        scroll: false,
      });
    },
    [router]
  );

  useEffect(() => {
    if (!router.isReady) return;
    setSection(parseWorkspace(router.query.workspace));
  }, [router.isReady, router.query.workspace]);

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetch("/api/vision/health", { cache: "no-store" });
      const data = (await response.json()) as SystemHealth;
      if (data.services) setSystemHealth(data);
    } catch {
      setSystemHealth({
        checkedAt: new Date().toISOString(),
        services: [],
        status: "offline",
      });
    }
  }, []);

  const refreshWorkloadAdmission = useCallback(async () => {
    try {
      const response = await fetch("/api/vision/workload-admission", {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Workload admission is unavailable.");
      const data = (await response.json()) as WorkloadAdmissionSnapshot;
      if (data.admissions) setWorkloadAdmission(data);
    } catch {
      setWorkloadAdmission(null);
    }
  }, []);

  const refreshSearchCoverage = useCallback(async () => {
    try {
      const response = await fetch("/api/vision/search-coverage", {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Search coverage is unavailable.");
      const data = (await response.json()) as SearchCoverageSnapshot;
      if (Array.isArray(data.sources) && data.summary) {
        setSearchCoverage(data);
        setSearchCoverageUnavailable(false);
      } else {
        throw new Error("Search coverage did not include source facts.");
      }
    } catch {
      // Keep the last complete observation visible; a transient query failure
      // must not turn known source facts into an invented empty state.
      setSearchCoverageUnavailable(true);
    }
  }, []);

  useEffect(() => {
    const onFullscreenChange = () =>
      setPresentationMode(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  useEffect(() => {
    void refreshHealth();
    const interval = window.setInterval(refreshHealth, 30_000);
    return () => window.clearInterval(interval);
  }, [refreshHealth]);

  useEffect(() => {
    void refreshWorkloadAdmission();
    const interval = window.setInterval(refreshWorkloadAdmission, 30_000);
    return () => window.clearInterval(interval);
  }, [refreshWorkloadAdmission]);

  useEffect(() => {
    if (section !== "system") return;
    void refreshSearchCoverage();
    const interval = window.setInterval(refreshSearchCoverage, 60_000);
    return () => window.clearInterval(interval);
  }, [refreshSearchCoverage, section]);

  useEffect(() => {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (
      storedTheme === "dark" ||
      storedTheme === "light" ||
      storedTheme === "system"
    ) {
      setThemePreference(storedTheme);
    }

    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const syncSystemTheme = () => setSystemPrefersDark(mediaQuery.matches);
    syncSystemTheme();
    mediaQuery.addEventListener?.("change", syncSystemTheme);
    return () => mediaQuery.removeEventListener?.("change", syncSystemTheme);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  useEffect(() => {
    const handleMonitoringSetup = (rawEvent: Event) => {
      const event = rawEvent as CustomEvent<PendingMonitoringSetup>;
      if (!event.detail?.sensorId || typeof event.detail.complete !== "function") return;
      event.preventDefault();
      setPendingMonitoringSetup((current) => {
        current?.complete();
        return event.detail;
      });
    };
    window.addEventListener("ctai:monitoring-setup", handleMonitoringSetup);
    return () => window.removeEventListener("ctai:monitoring-setup", handleMonitoringSetup);
  }, []);

  const navItems = useMemo(
    () => [
      { icon: IconHome, id: "home" as const, label: "Home" },
      { icon: IconVideo, id: "live" as const, label: "Live" },
      { icon: IconBellCog, id: "monitoring" as const, label: "Monitoring" },
      { icon: IconSearch, id: "explore" as const, label: "Explore" },
      { icon: IconBell, id: "events" as const, label: "Events" },
      { icon: IconBulb, id: "capabilities" as const, label: "Capabilities" },
      { icon: IconCpu, id: "system" as const, label: "System" },
    ],
    []
  );

  const openInvestigation = (query: string, camera?: VisionStream) => {
    setInvestigation({ camera, query });
    navigateToSection("explore");
  };

  const openLive = (
    stream?: VisionStream,
    options?: { focused?: boolean; panel?: "history" }
  ) => {
    setLiveTarget({
      focused: options?.focused ?? Boolean(stream),
      panel: options?.panel,
      streamId: stream?.streamId,
    });
    setLiveSession((session) => session + 1);
    navigateToSection("live");
  };

  const openEvents = () => {
    setEventsMode("activity");
    navigateToSection("events");
  };

  const openRules = (stream?: VisionStream) => {
    setMonitoringSourceId(stream?.sensorId ?? null);
    navigateToSection("monitoring");
  };

  const togglePresentationMode = async () => {
    setShowSystemHealth(false);
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      setPresentationMode((current) => !current);
    }
  };

  const selectTheme = (theme: ThemePreference) => {
    setThemePreference(theme);
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    setShowThemeMenu(false);
  };

  return (
    <div
      className={
        presentationMode
          ? "vi-app vi-brand-v2 is-presenting"
          : "vi-app vi-brand-v2"
      }
      data-theme={resolvedTheme}
      data-theme-preference={themePreference}
    >
      <aside className="vi-side-nav">
        <button
          className="vi-wordmark"
          type="button"
          onClick={() => navigateToSection("home")}
          aria-label="Vision Intelligence home"
        >
          <img src="/ctai-labs-horizontal-black.png" alt="" />
        </button>
        <div className="vi-product-label">
          <strong>Vision</strong>
          <span>Intelligence</span>
        </div>
        <nav className="vi-primary-nav" aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                aria-current={section === item.id ? "page" : undefined}
                className={section === item.id ? "is-active" : ""}
                onClick={() =>
                  item.id === "live" ? openLive() : navigateToSection(item.id)
                }
              >
                <Icon size={19} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <button
          className="vi-side-health"
          type="button"
          onClick={() => {
            setSystemPanel("overview");
            navigateToSection("system");
          }}
        >
          <span className={`is-${localProcessingStatus}`} />
          <div>
            <strong>Local edge</strong>
            <em>
              {systemHealth ? healthLabel(systemHealth.status) : "Checking"}
            </em>
          </div>
        </button>
      </aside>

      <header className="vi-context-bar">
        <div className="vi-context-title">
          <span>{sectionMeta[section].eyebrow}</span>
          <strong>{sectionMeta[section].title}</strong>
        </div>
        <div className="vi-context-actions">
          <button
            className="vi-processing-status"
            type="button"
            aria-label="System readiness"
            aria-expanded={showSystemHealth}
            onClick={() => setShowSystemHealth((current) => !current)}
          >
            <span className={`is-${localProcessingStatus}`} />
            <div>
              <strong>LOCAL PROCESSING</strong>
              <em>
                {systemHealth
                  ? `NVIDIA THOR · ${localProcessingStatus.toUpperCase()}`
                  : "CHECKING SERVICES"}
              </em>
            </div>
          </button>
          <div className="vi-theme-control">
            <button
              className="vi-theme-trigger"
              type="button"
              aria-label={`Appearance: ${themePreference}`}
              aria-expanded={showThemeMenu}
              aria-haspopup="menu"
              onClick={() => {
                setShowSystemHealth(false);
                setShowThemeMenu((current) => !current);
              }}
            >
              {resolvedTheme === "dark" ? (
                <IconMoon size={18} />
              ) : (
                <IconSun size={18} />
              )}
            </button>
            {showThemeMenu && (
              <div
                className="vi-theme-menu"
                role="menu"
                aria-label="Appearance options"
              >
                <span>Appearance</span>
                {(
                  [
                    ["light", "Light", IconSun],
                    ["dark", "Dark", IconMoon],
                    ["system", "System", IconDeviceDesktop],
                  ] as const
                ).map(([value, label, Icon]) => (
                  <button
                    key={value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={themePreference === value}
                    className={themePreference === value ? "is-active" : ""}
                    onClick={() => selectTheme(value)}
                  >
                    <Icon size={17} />
                    <span>{label}</span>
                    <i />
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            className="vi-presentation-button"
            type="button"
            onClick={() => void togglePresentationMode()}
          >
            <IconMaximize size={18} />
            {presentationMode ? "Exit Presentation" : "Presentation Mode"}
          </button>
          <button
            className="vi-more-button"
            type="button"
            aria-label="Open system overview"
            onClick={() => {
              setSystemPanel("overview");
              navigateToSection("system");
            }}
          >
            <IconDotsVertical size={20} />
          </button>
        </div>
      </header>

      {showSystemHealth && (
        <aside
          className="vi-system-popover"
          aria-label="System readiness details"
        >
          <div className="vi-system-popover-heading">
            <div>
              <strong>Thor readiness</strong>
              <span>
                {systemHealth
                  ? new Date(systemHealth.checkedAt).toLocaleTimeString()
                  : "Checking now"}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowSystemHealth(false)}
              aria-label="Close system readiness"
            >
              <IconX size={17} />
            </button>
          </div>
          {(systemHealth?.services ?? []).map((service) => (
            <div className="vi-system-service" key={service.key}>
              <i className={service.ok ? "is-online" : "is-offline"} />
              <span>{service.label}</span>
              <em>
                {service.ok ? `${service.latencyMs ?? "—"} ms` : "Unavailable"}
              </em>
            </div>
          ))}
          {systemHealth?.thor && (
            <div className="vi-thor-metrics">
              <div>
                <span>Accelerator</span>
                <strong>
                  {systemHealth.thor.gpuUtilizationPercent === null
                    ? acceleratorActive
                      ? "Active"
                      : "Unavailable"
                    : `${systemHealth.thor.gpuUtilizationPercent.toFixed(
                        0
                      )}% load`}
                </strong>
              </div>
              <div>
                <span>Video sources</span>
                <strong>
                  {systemHealth.thor.activeStreams ?? "Unavailable"}
                </strong>
              </div>
              <div>
                <span>Shared memory</span>
                <strong>
                  {formatMemory(systemHealth.thor.memoryUsedBytes)} /{" "}
                  {formatMemory(systemHealth.thor.memoryTotalBytes)}
                </strong>
              </div>
              <div>
                <span>GPU temperature</span>
                <strong>
                  {systemHealth.thor.gpuTemperatureC === null
                    ? "Unavailable"
                    : `${systemHealth.thor.gpuTemperatureC.toFixed(0)}°C`}
                </strong>
              </div>
            </div>
          )}
          {interactiveAdmission && (
            <div
              className={`vi-admission-popover is-${interactiveAdmission.decision}`}
            >
              <span>Visual compute lane</span>
              <strong>
                {interactiveAdmission.decision === "allow"
                  ? "Available"
                  : interactiveAdmission.decision === "queue"
                  ? "Waits for lane"
                  : "Unavailable"}
              </strong>
              <small>{interactiveAdmission.explanation}</small>
            </div>
          )}
          {!systemHealth && (
            <div className="vi-system-checking">
              <span className="vi-spinner" /> Checking local services
            </div>
          )}
          <button
            className="vi-popover-system-link"
            type="button"
            onClick={() => {
              setShowSystemHealth(false);
              setSystemPanel("overview");
              navigateToSection("system");
            }}
          >
            Open full system view <span>→</span>
          </button>
        </aside>
      )}

      <main className="vi-main">
        {section === "home" && (
          <HomeWorkspace
            agentApiUrl={searchData?.agentApiUrl}
            onExplore={openInvestigation}
            onOpenEvents={openEvents}
            onOpenLive={openLive}
            systemHealth={systemHealth}
            visualAnalystAvailable={visualAnalystAvailable}
            vstApiUrl={vstApiUrl}
          />
        )}
        {section === "live" && (
          <OperationsWorkspace
            agentApiUrl={searchData?.agentApiUrl}
            initialPanel={liveTarget.panel}
            initialStreamId={liveTarget.streamId}
            initialView={liveTarget.focused ? "focused" : "grid"}
            key={`live-${liveSession}`}
            onInvestigate={openInvestigation}
            onOpenActivity={openEvents}
            onOpenInsights={() => {
              setEventsMode("insights");
              navigateToSection("events");
            }}
            onOpenRules={openRules}
            visualAnalystAvailable={visualAnalystAvailable}
            vstApiUrl={vstApiUrl}
          />
        )}
        {section === "explore" && (
          <InvestigateWorkspace
            agentApiUrl={searchData?.agentApiUrl}
            initialRequest={investigation}
            mdxWebApiUrl={searchData?.mdxWebApiUrl}
            searchByImageEnabled={searchData?.mediaWithObjectsBbox === true}
            vstApiUrl={vstApiUrl}
          />
        )}
        {section === "events" && (
          <ActivityInsightsWorkspace
            initialMode={eventsMode}
            onModeChange={(mode) =>
              mode === "live" ? openLive() : setEventsMode(mode)
            }
            onOpenRules={() => openRules()}
            vstApiUrl={vstApiUrl}
          />
        )}
        {section === "capabilities" && (
          <CapabilitiesWorkspace
            onExplore={(query) => openInvestigation(query)}
            onOpenEvents={openEvents}
            onOpenLive={(mode = "grid") =>
              openLive(undefined, {
                focused: mode !== "grid",
                panel: mode === "history" ? "history" : undefined,
              })
            }
            onOpenRules={openRules}
            systemHealth={systemHealth}
          />
        )}
        {section === "monitoring" && (
          <AlertRulesWorkspace
            initialSourceId={monitoringSourceId}
            onManageSources={() => {
              setSystemPanel("sources");
              navigateToSection("system");
            }}
            onModeChange={(mode) => {
              if (mode === "monitor") {
                openLive();
                return;
              }
              setEventsMode(mode);
              navigateToSection("events");
            }}
            vstApiUrl={vstApiUrl}
          />
        )}
        {section === "system" && (
          <SystemWorkspace
            health={systemHealth}
            onPanelChange={setSystemPanel}
            onRefreshHealth={() => void refreshHealth()}
            panel={systemPanel}
            sources={
              <VideoManagement
                videoManagementData={videoManagementData}
                serverRenderTime={serverRenderTime}
                theme={resolvedTheme}
                isActive
              />
            }
            rules={
              <AlertRulesWorkspace
                onManageSources={() => setSystemPanel("sources")}
                vstApiUrl={vstApiUrl}
              />
            }
            searchCoverage={searchCoverage}
            searchCoverageUnavailable={searchCoverageUnavailable}
            workloadAdmissions={workloadAdmission?.admissions ?? null}
            workloadCheckedAt={workloadAdmission?.checkedAt ?? null}
          />
        )}
      </main>
      {pendingMonitoringSetup && (
        <MonitoringRuleWizard
          onClose={() => {
            pendingMonitoringSetup.complete({
              analysisProfileId: pendingMonitoringSetup.analysisProfileId,
              detectionEnabled: pendingMonitoringSetup.detectionEnabled ?? false,
              ruleCreated: false,
            });
            setPendingMonitoringSetup(null);
          }}
          onCreated={(rule: MonitoringRule) => {
            pendingMonitoringSetup.complete({
              analysisProfileId: pendingMonitoringSetup.analysisProfileId,
              detectionEnabled: pendingMonitoringSetup.detectionEnabled === true || rule.engine === "deepstream",
              ruleCreated: true,
            });
            setPendingMonitoringSetup(null);
          }}
          preselectedSourceId={pendingMonitoringSetup.sensorId}
          analysisProfileId={pendingMonitoringSetup.analysisProfileId}
          streams={[{
            isMain: true,
            metadata: {},
            name: pendingMonitoringSetup.name,
            sensorId: pendingMonitoringSetup.sensorId,
            streamId: pendingMonitoringSetup.sensorId,
            type: pendingMonitoringSetup.sourceKind === "live" ? "rtsp" : "file",
            url: pendingMonitoringSetup.streamUrl ?? "",
            vodUrl: "",
          }]}
          vstApiUrl={vstApiUrl}
        />
      )}
    </div>
  );
}
