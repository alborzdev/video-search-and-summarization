// SPDX-License-Identifier: MIT

import type { SystemHealth } from "./systemHealth";
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
  evidence: string[];
  icon: React.ComponentType<{ size?: number }>;
  id: CapabilityId;
  name: string;
  serviceKeys: string[];
}

interface CapabilitiesWorkspaceProps {
  onExplore: (query: string) => void;
  onOpenEvents: () => void;
  onOpenLive: (mode?: "focused" | "grid" | "history") => void;
  onOpenRules: () => void;
  systemHealth: SystemHealth | null;
}

const capabilities: Capability[] = [
  {
    action: "Try semantic search",
    description:
      "Describe an object, action, or situation in ordinary language. Cosmos Embed ranks relevant moments from recordings and retained live footage.",
    evidence: [
      "Natural-language retrieval",
      "Exact playable clips",
      "Live and recorded sources",
    ],
    icon: IconSearch,
    id: "search",
    name: "Semantic video search",
    serviceKeys: ["agent", "embedding"],
  },
  {
    action: "Ask a live source",
    description:
      "Ask a visual question about the current source or playback moment. Cosmos reasons over the footage and returns a grounded answer.",
    evidence: [
      "Current-frame reasoning",
      "Playback-aware questions",
      "Related evidence handoff",
    ],
    icon: IconMessageCircle,
    id: "reason",
    name: "Visual language understanding",
    serviceKeys: ["agent", "vlm"],
  },
  {
    action: "Open live monitoring",
    description:
      "Monitor up to eight connected sources, inspect retained live moments, and enable the installed detector profile only where it fits the scene.",
    evidence: [
      "RTSP monitoring",
      "Five-second semantic indexing",
      "Optional detection + tracking",
    ],
    icon: IconVideo,
    id: "live",
    name: "Live edge intelligence",
    serviceKeys: ["video", "embedding"],
  },
  {
    action: "Build an evidence set",
    description:
      "Select multiple search results, compare them with Cosmos, synthesize a conclusion with Nemotron, ask follow-ups, and export the investigation.",
    evidence: [
      "Multi-clip comparison",
      "Observed vs interpreted facts",
      "Saved HTML report",
    ],
    icon: IconBox,
    id: "evidence",
    name: "Evidence synthesis",
    serviceKeys: ["agent", "vlm", "llm"],
  },
  {
    action: "Open source history",
    description:
      "Build a source-scoped GraphRAG history from captioned moments, ask what changed over time, and jump back to cited timestamps.",
    evidence: [
      "Temporal GraphRAG",
      "Playable timestamp citations",
      "Source-scoped cleanup",
    ],
    icon: IconHistory,
    id: "history",
    name: "Video history",
    serviceKeys: ["agent", "llm"],
  },
  {
    action: "Configure alert rules",
    description:
      "Describe the condition worth surfacing. Live candidates are verified, consolidated, and kept with the associated clip for operator review.",
    evidence: [
      "Natural-language conditions",
      "VLM verification",
      "Consolidated incident evidence",
    ],
    icon: IconBell,
    id: "alerts",
    name: "Verified alerts",
    serviceKeys: ["analytics", "vlm"],
  },
];

export function CapabilitiesWorkspace({
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
  const ready = systemHealth ? readiness.every((service) => service?.ok) : null;

  const launch = () => {
    if (selected.id === "search") {
      onExplore("Find the most important recent activity.");
      return;
    }
    if (selected.id === "evidence") {
      onExplore("Show activity that may need operator review.");
      return;
    }
    if (selected.id === "alerts") {
      onOpenRules();
      return;
    }
    if (selected.id === "reason") {
      onOpenLive("focused");
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
        <span className="vi-eyebrow">Capability studio</span>
        <h1>What can this edge system understand?</h1>
        <p>
          Explore the actual workflows running on this Thor. Every demo below
          opens a live product surface and uses connected footage.
        </p>
      </div>

      <div className="vi-capability-layout">
        <nav className="vi-capability-index" aria-label="Capabilities">
          <span>Intelligence capabilities</span>
          {capabilities.map((capability, index) => {
            const Icon = capability.icon;
            const services = capability.serviceKeys.map((key) =>
              serviceMap.get(key)
            );
            const capabilityReady = systemHealth
              ? services.every((service) => service?.ok)
              : null;
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
                    {capabilityReady === null
                      ? "Checking local services"
                      : capabilityReady
                      ? "Ready on this Thor"
                      : "A required service needs attention"}
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
              <span>Working demo</span>
              <h2>{selected.name}</h2>
            </div>
            <div
              className={
                ready === false ? "vi-demo-state is-watch" : "vi-demo-state"
              }
            >
              {ready === false ? (
                <IconAlertCircle size={16} />
              ) : (
                <IconCheck size={16} />
              )}
              {ready === null
                ? "Checking"
                : ready
                ? "Ready"
                : "Needs attention"}
            </div>
          </div>
          <p className="vi-capability-description">{selected.description}</p>
          <div className="vi-capability-proof">
            <span>What you can verify</span>
            {selected.evidence.map((item) => (
              <div key={item}>
                <IconCheck size={16} /> {item}
              </div>
            ))}
          </div>
          <div className="vi-capability-services">
            <span>Local services used</span>
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
          </div>
          <div className="vi-capability-example">
            <IconSparkles size={19} />
            <div>
              <strong>Tradeshow prompt</strong>
              <p>
                {selected.id === "search"
                  ? "Try: “Find pedestrians near moving vehicles.”"
                  : selected.id === "reason"
                  ? "Open a source and ask: “What risks are visible right now?”"
                  : selected.id === "live"
                  ? "Connect a simulator RTSP feed and watch indexed moments become searchable."
                  : selected.id === "evidence"
                  ? "Select two or more clips, then ask what changed between them."
                  : selected.id === "history"
                  ? "Open History on a source and ask what happened over a longer period."
                  : "Create a precise condition, then review only verified candidates in Events."}
              </p>
            </div>
          </div>
          <button
            className="vi-capability-launch"
            type="button"
            onClick={launch}
          >
            {selected.action} <IconArrowRight size={18} />
          </button>
        </article>
      </div>
    </section>
  );
}
