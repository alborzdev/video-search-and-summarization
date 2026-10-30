// SPDX-License-Identifier: MIT
import { animateViewChange } from './viewTransition';

import { DashPlaybackCapability } from "./DashPlaybackCapability";

import type { MonitoringRule } from "./monitoringRules";
import type { SystemPanel } from "./SystemWorkspace";
import { demoServiceChecks, formatMemory, healthLabel, type SystemHealth } from "./systemHealth";
import type { CityWorkspaceView } from './smart-city/types';
import type { PrimarySection, VisionStream } from "./types";
import {
  IconShieldCheck,
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
  IconRoute,
  IconX,
} from "@tabler/icons-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/router";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { parseWorkspace, workspaceHref } from "../../utils/workspaceRoute";
import type {
  WorkloadAdmissionFacts,
  WorkloadAdmissions,
} from "../../server/vision/workloadAdmission";
import type { SearchCoverageSnapshot } from "../../server/vision/searchCoverage";
import { ClearHistoryControl } from "./ClearHistoryControl";

const workspaceLoading = (workspace: string) => () => (
  <div className="vi-workspace-loading" role="status" aria-live="polite">
    <span className="vi-spinner" /> Loading {workspace}…
  </div>
);

const HomeWorkspace = dynamic(
  () => import("./HomeWorkspace").then((module) => module.HomeWorkspace),
  { loading: workspaceLoading("Home") }
);
const DefenseWorkspace = dynamic(
  () => import("./DefenseWorkspace").then((module) => module.DefenseWorkspace),
  { loading: workspaceLoading("Defense") }
);
const SmartCityWorkspace = dynamic(
  () => import("./SmartCityWorkspace").then((module) => module.SmartCityWorkspace),
  { loading: workspaceLoading("Smart City") }
);
const GuidedDemoWorkspace = dynamic(
  () => import("./GuidedDemoWorkspace").then((module) => module.GuidedDemoWorkspace),
  { loading: workspaceLoading("Video workflow") }
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
const VssStoryWorkspace = dynamic(
  () => import("./VssStoryWorkspace").then((module) => module.VssStoryWorkspace),
  { loading: workspaceLoading("Capabilities") }
);
const DefenseStoryWorkspace = dynamic(
  () => import("./DefenseStoryWorkspace").then((module) => module.DefenseStoryWorkspace),
  { ssr: false }
);
const SmartCityStoryWorkspace = dynamic(
  () => import("./SmartCityStoryWorkspace").then((module) => module.SmartCityStoryWorkspace),
  { loading: workspaceLoading("Smart City story") }
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
    import("@nv-metropolis-bp-vss-ui/video-management").then(
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
    defense: { eyebrow: "", title: "Defense" },
    'smart-city': { eyebrow: "", title: "Smart City" },
    capabilities: { eyebrow: "Video Search & Summarization", title: "What it can do" },
    events: { eyebrow: "Evidence-led review", title: "Events & reports" },
    explore: { eyebrow: "Search video in your own words", title: "Search video" },
    home: { eyebrow: "", title: "Digital twin analytics" },
    guided: { eyebrow: "", title: "Video workflow" },
    live: { eyebrow: "", title: "Live cameras" },
    monitoring: { eyebrow: "Rules that create incidents", title: "Alert rules" },
    system: { eyebrow: "On-device runtime", title: "System" },
  };

export default function VisionIntelligenceApp({
  alertsData,
  searchData,
  serverRenderTime,
  videoManagementData,
}: VisionIntelligenceAppProps) {
  const router = useRouter();
  const primaryNav = useRef<HTMLElement>(null);
  const cityScroll = useRef<HTMLDivElement>(null);
  const cityStory = useRef<HTMLElement>(null);
  const [section, setSection] = useState<PrimarySection>(() =>
    parseWorkspace(router.query.workspace)
  );
  const [eventsMode, setEventsMode] = useState<"activity" | "insights">(
    "activity"
  );
  const [investigation, setInvestigation] =
    useState<InvestigationRequest | null>(null);
  const [hasOpenedInvestigation, setHasOpenedInvestigation] = useState(false);
  const [liveTarget, setLiveTarget] = useState<LiveTarget>({ focused: false });
  const [liveSession, setLiveSession] = useState(0);
  const [monitoringSourceId, setMonitoringSourceId] = useState<string | null>(null);
  const [pendingMonitoringSetup, setPendingMonitoringSetup] = useState<PendingMonitoringSetup | null>(null);
  const [presentationMode, setPresentationMode] = useState(false);
  const [cityView, setCityView] = useState<CityWorkspaceView>('overview');
  const changeCityView = useCallback((view: CityWorkspaceView) => {
    animateViewChange(() => {
      setCityView(view);
      cityScroll.current?.scrollTo?.({ top: 0, behavior: "auto" });
    });
  }, []);
  const showCityStory = useCallback(() => {
    const container = cityScroll.current;
    const story = cityStory.current;
    if (!container || !story) return;
    container.scrollTo({
      top: story.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }, []);
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
    (section === "smart-city" || section === "defense") ? "dark" : themePreference === "system"
      ? systemPrefersDark
        ? "dark"
        : "light"
      : themePreference;
  const interactiveAdmission =
    workloadAdmission?.admissions.current_visual_question;

  const navigateToSection = useCallback(
    (nextSection: PrimarySection) => {
      animateViewChange(() => {
        if (nextSection !== "monitoring") setMonitoringSourceId(null);
        setSection(nextSection);
        window.scrollTo({ top: 0, left: 0, behavior: "instant" as ScrollBehavior });
        if (!router.isReady) return;
        void router.push(workspaceHref(nextSection, router.query), undefined, {
          shallow: true,
          scroll: false,
        });
      });
    },
    [router]
  );

  useEffect(() => {
    if (!router.isReady) return;
    setSection(parseWorkspace(router.query.workspace));
  }, [router.isReady, router.query.workspace]);

  useEffect(() => {
    if (section === "explore") setHasOpenedInvestigation(true);
  }, [section]);

  useEffect(() => {
    if (window.matchMedia?.("(max-width: 900px)").matches) {
      primaryNav.current?.querySelector('[aria-current="page"]')?.scrollIntoView?.({
        block: "nearest", inline: "nearest",
      });
    }
  }, [section]);

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
    const refreshAfterClear = (event: Event) => {
      const status = (event as CustomEvent).detail?.job?.status;
      if (status !== "complete" && status !== "partial") return;
      void refreshHealth();
      void refreshSearchCoverage();
      void refreshWorkloadAdmission();
    };
    window.addEventListener("vision:history-cleared", refreshAfterClear);
    return () => window.removeEventListener("vision:history-cleared", refreshAfterClear);
  }, [refreshHealth, refreshSearchCoverage, refreshWorkloadAdmission]);

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
      { icon: IconRoute, id: "smart-city" as const, label: "Smart City" },
      { icon: IconShieldCheck, id: "defense" as const, label: "Defense" },
      { icon: IconVideo, id: "home" as const, label: "Live view" },
      { icon: IconRoute, id: "guided" as const, label: "Video workflow" },
      { icon: IconSearch, id: "explore" as const, label: "Search video" },
      { icon: IconVideo, id: "live" as const, label: "Live cameras" },
      { icon: IconBell, id: "events" as const, label: "Events & reports" },
      { icon: IconBellCog, id: "monitoring" as const, label: "Alert rules" },
      { icon: IconBulb, id: "capabilities" as const, label: "What it can do" },
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
    <DashPlaybackCapability.Provider value={systemHealth?.videoPlayback?.dashEnabled === true}>
    <div
      className={
        presentationMode
          ? `vi-app vi-brand-v2 vi-tradeshow is-presenting${section === "capabilities" ? " vi-story-mode" : section === "guided" ? " vi-guided-mode" : ""}`
          : `vi-app vi-brand-v2 vi-tradeshow${section === "capabilities" ? " vi-story-mode" : section === "guided" ? " vi-guided-mode" : ""}`
      }
      data-workspace={section}
      data-theme={resolvedTheme}
      data-theme-preference={themePreference}
    >
      {section === "capabilities" && ["smart-city", "defense"].includes(String(router.query.story)) && <style jsx global>{`
        .vi-brand-v2.vi-tradeshow.vi-story-mode.is-presenting { grid-template-columns: minmax(0, 1fr); }
      `}</style>}
      {section === "smart-city" && <style jsx global>{`
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] { --vi-bg:#151617; --vi-surface:#1b1d1f; --vi-surface-hover:#232629; --vi-border:#303438; --vi-border-strong:#475057; --vi-text:#eff2f4; --vi-muted:#a3acb3; --vi-positive:#37d5c1; --vi-accent:#37d5c1; --vi-accent-strong:#58dfce; background:#151617; height:100dvh; min-height:0; max-height:100dvh; overflow:hidden; grid-template-columns:228px minmax(0,1fr); grid-template-rows:64px minmax(0,1fr); }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-side-nav { background:#151719; border-color:#303438; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-primary-nav { gap:6px; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-primary-nav button { min-height:46px; font-size:14px; border-radius:6px; color:#aab3ba; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-primary-nav button.is-active { background:#222c30; color:#f2f5f6; box-shadow:inset 3px 0 #37d5c1; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-primary-nav button.is-active svg { color:#37d5c1; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-bar { background:#151719; padding-inline:24px; gap:24px; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-title { flex:none; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-title strong { font-size:23px; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status { min-height:32px; padding:0 14px; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status strong { font-size:13px; font-weight:500; color:#c1c9cf; white-space:nowrap; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status em { display:none; }
        .vi-city-tabs { display:flex; align-self:stretch; align-items:stretch; gap:22px; margin-right:auto; }
        .vi-city-tabs button { padding:0 8px; border:0; border-bottom:2px solid transparent; color:#a7b1b8; background:transparent; font-family:inherit; font-size:14px; font-weight:500; line-height:1.3; cursor:pointer; white-space:nowrap; }
        .vi-city-tabs button[aria-current=page] { border-bottom-color:#37d5c1; color:#f2f4f5; }
        .vi-city-tabs button:hover { color:#fff; }
        .vi-city-tabs button:focus-visible { outline:2px solid #37d5c1; outline-offset:-4px; }
        @media(min-width:901px) and (max-width:1450px) { .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status { display:none; } .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-bar { gap:16px; } .vi-city-tabs { gap:10px; } }
        @media(min-width:1201px) { .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status { display:flex; } }
        @media(max-width:1100px) { .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-title strong { font-size:18px; } .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-presentation-button { width:36px; min-width:36px; padding:0; font-size:0; } }
        @media(max-width:900px) { .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] { grid-template-columns:minmax(0,1fr); } .vi-city-tabs { gap:4px; } .vi-city-tabs button { font-size:12px; padding-inline:5px; } .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status { display:none; } }

        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"].is-presenting { grid-template-columns: minmax(0, 1fr); }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-bar { height: 64px; min-height: 64px; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-theme-control { display: none; }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-main { min-width: 0; padding: 0; }
        .vi-city-scroll { height:100%; min-height:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior-y:contain; }
        .vi-city-dashboard { height:100%; min-height:0; }
        .vi-city-scroll[data-overview="true"] .vi-city-dashboard { height:calc(100% - 42px); }
        .vi-city-story-cue { width:100%; height:42px; border:0; border-top:1px solid #303438; background:#171a1b; color:#a9dcd2; font:inherit; font-size:12px; cursor:pointer; }
        .vi-city-story-cue:hover { background:#202a29; color:#e8fffa; }
        .vi-city-story-cue:focus-visible { outline:2px solid #37d5c1; outline-offset:-3px; }
        @media (max-width: 900px) {
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] { grid-template-rows:104px minmax(0,1fr); }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-bar { display:grid; grid-template-columns:minmax(0,1fr) 36px; grid-template-rows:40px 44px; height:104px; min-height:104px; padding:8px 12px 0; gap:4px 8px; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-title { grid-column:1; grid-row:1; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-actions { grid-column:2; grid-row:1; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-city-tabs { grid-column:1/-1; grid-row:2; width:100%; justify-content:space-between; margin:0; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-city-tabs button { font-size:13px; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-main { overflow:auto; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"]:not(.is-presenting) .vi-main { padding-bottom: 76px; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-bar { padding-inline: 12px; gap: 8px; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-title { flex: 1; min-width: 0; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-context-actions { flex: 0 0 auto; min-width: 0; gap: 4px; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-processing-status { min-width: 28px; padding: 0; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-presentation-button { flex-shrink: 0; width: 36px; min-width: 36px; padding: 0; margin:0; font-size: 0; }
          .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-more-button { display: none; }
        }
        .vi-brand-v2.vi-tradeshow[data-workspace="smart-city"] .vi-main { overflow:hidden; }
        @media(max-width:760px) { .vi-city-dashboard, .vi-city-scroll[data-overview="true"] .vi-city-dashboard { height:auto; min-height:100%; } }
      `}</style>}
      {section === "defense" && <style jsx global>{`
        .vi-brand-v2.vi-tradeshow[data-workspace="defense"] .vi-main { min-width: 0; padding: 0; }
        .vi-brand-v2.vi-tradeshow[data-workspace="defense"].is-presenting { grid-template-columns: minmax(0, 1fr); }
      `}</style>}
      <aside className="vi-side-nav">
        <button
          className="vi-wordmark"
          type="button"
          onClick={() => navigateToSection("home")}
          aria-label="Vision Intelligence home"
        >
          <img src={resolvedTheme === "dark" ? "/ctai-labs-horizontal-white.png" : "/ctai-labs-horizontal-black.png"} alt="CTAI Labs" />
        </button>
        <div className="vi-product-label">
          <strong>Vision</strong>
          <span>Intelligence</span>
        </div>
        <nav ref={primaryNav} className="vi-primary-nav" aria-label="Primary navigation">
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
          <span className={presentationMode ? "is-presentation" : `is-${localProcessingStatus}`} />
          <div>
            <strong>Video + AI</strong>
            <em>
              On this device
            </em>
          </div>
        </button>
      </aside>

      <header className="vi-context-bar">
        <div className="vi-context-title">
          {section === "smart-city" && presentationMode ? <div style={{ display: "flex", alignItems: "center", gap: 16 }}><img src="/ctai-labs-horizontal-white.png" alt="CTAI Labs" style={{ width: "clamp(70px, 10vw, 140px)", height: "auto" }} /><strong style={{ whiteSpace: "nowrap" }}>Smart City</strong></div> : <><span>{sectionMeta[section].eyebrow}</span><strong style={section === "smart-city" ? { whiteSpace: "nowrap" } : undefined}>{sectionMeta[section].title}</strong></>}
        </div>
        {section === 'smart-city' && <nav className="vi-city-tabs" aria-label="Smart City views">{(['overview', 'measurements', 'search', 'edge'] as const).map(view => <button key={view} type="button" aria-current={cityView === view ? 'page' : undefined} onClick={() => changeCityView(view)}>{view === 'overview' ? 'Overview' : view === 'measurements' ? 'Measurements' : view === 'edge' ? 'Why edge AI' : 'Search & reports'}</button>)}</nav>}
        <div className="vi-context-actions">
          <ClearHistoryControl hideTrigger={section === "smart-city" || section === "defense"} />
          <button
            className="vi-processing-status"
            type="button"
            aria-label="System readiness"
            aria-expanded={showSystemHealth}
            onClick={() => setShowSystemHealth((current) => !current)}
          >
            <span className={presentationMode ? "is-presentation" : `is-${localProcessingStatus}`} />
            <div>
              <strong>{section === 'smart-city' ? `On device · ${systemHealth?.hardwareProfile === 'DGX-SPARK' ? 'DGX Spark' : systemHealth?.thor ? 'Jetson Thor' : 'Local AI'}` : 'LOCAL PROCESSING'}</strong>
              <em>
                {presentationMode
                  ? "ON THIS DEVICE"
                  : systemHealth
                  ? `LOCAL AI · ${localProcessingStatus.toUpperCase()}`
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
          {(section !== "smart-city" || presentationMode) && <button
            className="vi-presentation-button"
            type="button"
            onClick={() => void togglePresentationMode()}
          >
            <IconMaximize size={18} />
            {presentationMode ? "Exit Presentation" : "Presentation Mode"}
          </button>}
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
              <strong>Local readiness</strong>
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
          {systemHealth && (
            <section className="vi-demo-service-checks" aria-label="Demo service checks">
              <strong>Services for your demo</strong>
              {demoServiceChecks(systemHealth).map((check) => (
                <div className="vi-system-service" key={check.label}>
                  <i className={check.status === "available" ? "is-online" : check.status === "unavailable" ? "is-offline" : "is-unknown"} />
                  <span>{check.label}</span>
                  <em>{check.status === "available" ? "Available" : check.status === "unavailable" ? "Unavailable" : check.status === "not-selected" ? "Not selected" : "Not checked"}</em>
                </div>
              ))}
              <p>Service checks only. Camera connection, analysis settings and compute capacity also affect live monitoring.</p>
            </section>
          )}
          <details className="vi-service-details">
            <summary>Technical service checks</summary>
          {(systemHealth?.services ?? []).map((service) => (
            <div className="vi-system-service" key={service.key}>
              <i className={service.selected === false ? "is-unknown" : service.ok ? "is-online" : "is-offline"} />
              <span>{service.label}</span>
              <em>
                {service.selected === false ? "Not selected" : service.ok ? `${service.latencyMs ?? "—"} ms` : "Unavailable"}
              </em>
            </div>
          ))}
          </details>
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
        {section === "defense" && <DefenseWorkspace onOpenExplainer={() => { setSection("capabilities"); void router.push(workspaceHref("capabilities", { ...router.query, story: "defense" }), undefined, { shallow: true, scroll: false }); }} onOpenSources={() => { setSystemPanel("sources"); navigateToSection("system"); }} />}
        {section === "smart-city" && (
          <div ref={cityScroll} className="vi-city-scroll" data-city-scroll data-overview={cityView === "overview"}>
            <div className="vi-city-dashboard">
              <SmartCityWorkspace activeView={cityView} onViewChange={changeCityView} vstApiUrl={vstApiUrl} onOpenExplainer={showCityStory} />
            </div>
            {cityView === "overview" && <>
              <button type="button" className="vi-city-story-cue" onClick={showCityStory}>Scroll to explore how Smart City works ↓</button>
              <section ref={cityStory} aria-label="How Smart City works">
                <SmartCityStoryWorkspace
                  embedded
                  onOpenDemo={() => changeCityView("overview")}
                  onOpenGeneral={() => { setSection("capabilities"); void router.push(workspaceHref("capabilities", { ...router.query, story: "general" }), undefined, { shallow: true, scroll: false }); }}
                  systemHealth={systemHealth}
                />
              </section>
            </>}
          </div>
        )}
        {section === "guided" && (
          <GuidedDemoWorkspace
            agentApiUrl={searchData?.agentApiUrl}
            mdxWebApiUrl={searchData?.mdxWebApiUrl}
            searchByImageEnabled={searchData?.mediaWithObjectsBbox === true}
            visualAnalystAvailable={visualAnalystAvailable}
            vstApiUrl={vstApiUrl}
            onOpenLive={openLive}
            onOpenSystem={() => { setSystemPanel("sources"); navigateToSection("system"); }}
            onOpenExplainer={() => navigateToSection("capabilities")}
          />
        )}
        {section === "home" && (
          <HomeWorkspace
            agentApiUrl={searchData?.agentApiUrl}
            onExplore={openInvestigation}
            onOpenEvents={openEvents}
            onOpenRules={openRules}
            onOpenLive={openLive}
            onOpenSystem={() => navigateToSection("system")}
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
        {(section === "explore" || hasOpenedInvestigation) && (
          <div hidden={section !== "explore"}>
          <InvestigateWorkspace
            isActive={section === "explore"}
            agentApiUrl={searchData?.agentApiUrl}
            initialRequest={investigation}
            mdxWebApiUrl={searchData?.mdxWebApiUrl}
            searchByImageEnabled={searchData?.mediaWithObjectsBbox === true}
            vstApiUrl={vstApiUrl}
          />
          </div>
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
        {section === "capabilities" && router.query.story === "smart-city" && (
          <SmartCityStoryWorkspace
            onOpenDemo={() => navigateToSection("smart-city")}
            onOpenGeneral={() => void router.push(workspaceHref("capabilities", { ...router.query, story: "general" }), undefined, { shallow: true, scroll: false })}
            systemHealth={systemHealth}
          />
        )}
        {section === "capabilities" && router.query.story === "defense" && (
          <DefenseStoryWorkspace
            onOpenDemo={() => navigateToSection("defense")}
            onOpenGeneral={() => void router.push(workspaceHref("capabilities", { ...router.query, story: "general" }), undefined, { shallow: true, scroll: false })}
            systemHealth={systemHealth}
          />
        )}
        {section === "capabilities" && !["smart-city", "defense"].includes(String(router.query.story)) && (
          <VssStoryWorkspace
            onOpenDemo={() => navigateToSection("guided")}
            onOpenDefenseStory={() => void router.push(workspaceHref("capabilities", { ...router.query, story: "defense" }), undefined, { shallow: true, scroll: false })}
            onOpenCityStory={() => void router.push(workspaceHref("capabilities", { ...router.query, story: "smart-city" }), undefined, { shallow: true, scroll: false })}
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
    </DashPlaybackCapability.Provider>
  );
}
