// SPDX-License-Identifier: MIT

import type { SystemHealth } from "./systemHealth";
import type { WorkloadAdmissions, WorkloadClass } from "../../server/vision/workloadAdmission";
import type { SearchCoverageSnapshot } from "../../server/vision/searchCoverage";
import {
  IconAlertCircle,
  IconArrowRight,
  IconBell,
  IconBox,
  IconCheck,
  IconHistory,
  IconMessageCircle,
  IconSearch,
  IconSparkles,
  IconVideo,
} from "@tabler/icons-react";
import React, { useMemo, useState } from "react";

type CapabilityId =
  | "search"
  | "reason"
  | "live"
  | "evidence"
  | "history"
  | "alerts";

interface Capability {
  action: string;
  description: string;
  example: string;
  businessUse: string;
  evidence: string[];
  icon: React.ComponentType<{ size?: number }>;
  id: CapabilityId;
  name: string;
  serviceKeys: string[];
}

interface CapabilitiesWorkspaceProps {
  admissions?: WorkloadAdmissions;
  searchCoverage?: SearchCoverageSnapshot | null;
  onExplore: (query: string) => void;
  onOpenEvents: () => void;
  onOpenLive: (mode?: "focused" | "grid" | "history") => void;
  onOpenRules: () => void;
  systemHealth: SystemHealth | null;
}

const capabilities: Capability[] = [
  {
    id: "search", name: "Find a moment", icon: IconSearch,
    action: "Search existing footage",
    description: "Describe what you want to find. Search returns matching video clips you can play and check.",
    example: "Find a person carrying a box.",
    businessUse: "Warehouse teams: locate handling activity without watching an entire recording.",
    evidence: ["Search in everyday language", "Play the matching moment", "Use indexed recordings or retained camera footage"],
    serviceKeys: ["agent", "embedding"],
  },
  {
    id: "reason", name: "Ask about a clip", icon: IconMessageCircle,
    action: "Find a clip to ask about",
    description: "Choose a clip and ask a question. The AI inspects its visible content and links the answer back to the video for review.",
    example: "What activity is visible in this clip?",
    businessUse: "Retail and operations teams: inspect visible activity around a shelf, counter or work area.",
    evidence: ["Ask a specific question", "Read the AI observation", "Check the same footage yourself"],
    serviceKeys: ["agent", "vlm"],
  },
  {
    id: "live", name: "Watch camera activity", icon: IconVideo,
    action: "Check connected cameras",
    description: "Bring camera views into one local workspace. With a connected feed and configured analysis, new activity can become searchable.",
    example: "Connect a camera, then find an activity that just happened.",
    businessUse: "Warehouses and transport sites: review activity across camera views from one place.",
    evidence: ["View connected cameras", "Search retained moments", "Add supported detection and tracking"],
    serviceKeys: ["video", "embedding"],
  },
  {
    id: "evidence", name: "Review and share", icon: IconBox,
    action: "Choose footage to review",
    description: "Review an AI answer against its footage, add your notes, and save a briefing someone else can check. Keep the observed activity and the supporting video together.",
    example: "What moves in this clip? Save the reviewed answer with its evidence.",
    businessUse: "Operations reviews: share the footage behind a finding with the next person who needs to act.",
    evidence: ["Check the answer against the clip", "Keep playable references", "Save a report and copy its briefing"],
    serviceKeys: ["agent", "vlm", "llm"],
  },
  {
    id: "history", name: "Review activity over time", icon: IconHistory,
    action: "Check source history",
    description: "Once a source has a captioned history, ask about activity over a longer period and return to the referenced moments.",
    example: "What activity was recorded during this period?",
    businessUse: "Manufacturing and logistics teams: review a shift using retained activity history.",
    evidence: ["Build history for one source", "Ask about changes over time", "Return to cited moments"],
    serviceKeys: ["agent", "vlm", "llm"],
  },
  {
    id: "alerts", name: "Flag activity for review", icon: IconBell,
    action: "Set up an alert rule",
    description: "Define the activity you want surfaced. A configured live workflow can collect candidates and supporting footage for an operator to review.",
    example: "Flag a person entering a defined area, then review the clip.",
    businessUse: "Site operations: focus attention on a defined condition instead of watching every camera continuously.",
    evidence: ["Define a condition and source", "Inspect event candidates", "Review the supporting footage"],
    serviceKeys: ["analytics", "vlm"],
  },
];

export function CapabilitiesWorkspace({
  admissions,
  searchCoverage,
  onExplore,
  onOpenEvents,
  onOpenLive,
  onOpenRules,
  systemHealth,
}: CapabilitiesWorkspaceProps) {
  const [selectedId, setSelectedId] = useState<CapabilityId>("search");
  const selected = capabilities.find(
    (capability) => capability.id === selectedId
  )!;
  const serviceMap = useMemo(
    () =>
      new Map(systemHealth?.services.map((service) => [service.key, service])),
    [systemHealth]
  );
  const readiness = selected.serviceKeys.map((key) => serviceMap.get(key));
  const capabilityStatus = (capability: Capability) => {
    const status = (label: string, explanation: string, available = false) => ({ label, explanation, available });
    if (!systemHealth) return status("Checking services", "Checking this device’s local services.");
    if (capability.serviceKeys.some((key) => !serviceMap.get(key)?.ok)) {
      return status("Service unavailable", "A required local service is unavailable. Check System before starting this workflow.");
    }
    const workload: Partial<Record<CapabilityId, WorkloadClass>> = {
      reason: "evidence_analysis", evidence: "evidence_analysis",
      history: "long_video_history_build", alerts: "live_vlm_alert",
    };
    const admission = workload[capability.id] ? admissions?.[workload[capability.id]!] : undefined;
    if (workload[capability.id] && !admission) {
      return status("Availability unverified", "Local services are running. Current compute availability has not been verified.");
    }
    if (admission && admission.decision !== "allow") {
      return status(admission.decision === "queue" ? "Compute busy" : "Unavailable now", admission.explanation);
    }
    if (capability.id === "live" || capability.id === "alerts") {
      return status("Check sources", capability.id === "live"
        ? "Local services are available. Open Live to check the camera connection and whether analysis is running. Service health alone does not confirm live monitoring."
        : "Check that a rule is enabled and its source is being analyzed. Available services do not mean alerts are actively monitored.");
    }
    if (capability.id === "search" || capability.id === "reason" || capability.id === "evidence") {
      const fresh = searchCoverage && Date.now() - Date.parse(searchCoverage.generatedAt) < 90_000;
      if (!fresh) return status("Checking evidence", "Retained, indexed footage has not yet been verified. Check source coverage in System.");
      const usable = searchCoverage.sources.some((source) => source.indexStatus === "indexed" && source.recordingStatus === "retained");
      if (!usable) return status("Footage needed", "No source currently has both a confirmed semantic index and retained recording. Add or index footage before demonstrating this workflow.");
      return status("Evidence available", "A source has indexed moments and retained video. Select a clip to verify its exact recording interval.", true);
    }
    return status("Choose a source", capability.id === "history"
      ? "Compute is available. Choose a source to check its existing history or build one; history is not generated automatically."
      : "Compute is available. Choose playable footage to ask a question about the visible scene.");
  };
  const selectedStatus = capabilityStatus(selected);

  const launch = () => {
    if (selected.id === "search") {
      onExplore("person carrying a box");
      return;
    }
    if (selected.id === "evidence") {
      onExplore("person carrying a box");
      return;
    }
    if (selected.id === "alerts") {
      onOpenRules();
      return;
    }
    if (selected.id === "reason") {
      onExplore("person carrying a box");
      return;
    }
    if (selected.id === "history") {
      onOpenLive("history");
      return;
    }
    if (selected.id === "live") {
      onOpenLive("grid");
      return;
    }
    onOpenEvents();
  };

  return (
    <section className="vi-capabilities">
      <div className="vi-page-intro">
        <span className="vi-eyebrow">Video AI in practice</span>
        <h1>What would you like to do with your video?</h1>
        <p>
          Start with a recording, or explore what a connected camera workflow can add.
          Each task shows what is available on this device today.
        </p>
      </div>

      <div className="vi-capability-layout">
        <nav className="vi-capability-index" aria-label="Capabilities">
          <span>Choose a task</span>
          {capabilities.map((capability, index) => {
            const Icon = capability.icon;
            const currentStatus = capabilityStatus(capability);
            return (
              <button
                className={capability.id === selectedId ? "is-active" : ""}
                type="button"
                key={capability.id}
                onClick={() => setSelectedId(capability.id)}
              >
                <small>{String(index + 1).padStart(2, "0")}</small>
                <Icon size={20} />
                <span>
                  <strong>{capability.name}</strong>
                  <em>
                    {currentStatus.label}
                  </em>
                </span>
                <IconArrowRight size={17} />
              </button>
            );
          })}
        </nav>

        <article className="vi-capability-demo">
          <div className="vi-capability-demo-head">
            <div className="vi-capability-icon">
              <selected.icon size={25} />
            </div>
            <div>
              <span>Local workflow</span>
              <h2>{selected.name}</h2>
            </div>
            <div
              className={
                selectedStatus.available ? "vi-demo-state" : "vi-demo-state is-watch"
              }
            >
              {!selectedStatus.available ? (
                <IconAlertCircle size={16} />
              ) : (
                <IconCheck size={16} />
              )}
              {selectedStatus.label}
            </div>
          </div>
          <p className="vi-capability-description">{selected.description}</p>
          <div className="vi-capability-business"><span>Where this helps</span><p>{selected.businessUse}</p></div>
          <p className="vi-capability-readiness" role="status">{selectedStatus.explanation}</p>
          <div className="vi-capability-proof">
            <span>What you get</span>
            {selected.evidence.map((item) => (
              <div key={item}>
                <IconCheck size={16} /> {item}
              </div>
            ))}
          </div>
          <details className="vi-capability-services">
            <summary>How it runs locally</summary>
            <div>
              {readiness.map((service, index) => (
                <span
                  className={service?.ok ? "is-ready" : ""}
                  key={selected.serviceKeys[index]}
                >
                  <i /> {service?.label ?? selected.serviceKeys[index]}
                </span>
              ))}
            </div>
          </details>
          <div className="vi-capability-example">
            <IconSparkles size={19} />
            <div>
              <strong>Example question or action</strong>
              <p>{selected.example}</p>
            </div>
          </div>
          <div className="vi-capability-actions">
          <button
            className="vi-capability-launch"
            type="button"
            onClick={launch}
          >
            {selected.action} <IconArrowRight size={18} />
          </button>
          {selected.id === "evidence" && (
            <button className="vi-button" type="button" onClick={onOpenEvents}>
              View saved reports <IconArrowRight size={18} />
            </button>
          )}
          </div>
        </article>
      </div>
    </section>
  );
}
