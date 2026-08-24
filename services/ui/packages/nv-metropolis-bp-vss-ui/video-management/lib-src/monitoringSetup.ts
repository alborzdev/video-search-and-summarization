// SPDX-License-Identifier: MIT

export const MONITORING_SETUP_EVENT = "ctai:monitoring-setup";

export interface MonitoringSetupSource {
  analysisProfileId: string;
  blocking: boolean;
  detectionEnabled?: boolean;
  name: string;
  sensorId: string;
  sourceKind: "live" | "recorded";
  streamUrl?: string;
}

export interface MonitoringSetupResult {
  analysisProfileId: string;
  detectionEnabled: boolean;
  ruleCreated: boolean;
}

export interface MonitoringSetupEventDetail extends MonitoringSetupSource {
  complete: (result?: Partial<MonitoringSetupResult>) => void;
}

/**
 * Offers the shell a guided monitoring step. A blocking recorded upload waits
 * here before post-processing so its ROI is already active when RTVI-CV runs.
 * When the custom Vision Intelligence shell is not mounted, processing carries
 * on immediately and the stock video-management package remains standalone.
 */
export function requestMonitoringSetup(
  source: MonitoringSetupSource,
): Promise<MonitoringSetupResult> {
  const fallback = {
    analysisProfileId: source.analysisProfileId,
    detectionEnabled: source.detectionEnabled ?? false,
    ruleCreated: false,
  };
  // Recorded semantic-only sources do not have an event-producing detector
  // pass, so a structured area/proximity rule cannot be evaluated. Do not
  // interrupt upload with a rule wizard that has no compatible condition.
  // Live semantic sources still use this handshake because they can create a
  // VLM-backed visual rule.
  if (source.sourceKind === 'recorded' && !fallback.detectionEnabled) {
    return Promise.resolve(fallback);
  }
  if (typeof window === "undefined" || typeof window.CustomEvent !== "function") {
    return Promise.resolve(fallback);
  }

  return new Promise((resolve) => {
    let settled = false;
    let timeoutId: number | undefined;
    const complete = (result: Partial<MonitoringSetupResult> = {}) => {
      if (settled) return;
      settled = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      resolve({ ...fallback, ...result });
    };
    const event = new CustomEvent<MonitoringSetupEventDetail>(MONITORING_SETUP_EVENT, {
      cancelable: true,
      detail: { ...source, complete },
    });
    const handled = !window.dispatchEvent(event);
    if (!handled) {
      complete();
      return;
    }
    if (settled) return;
    // A dismissed shell or interrupted browser session must never leave an
    // uploaded video waiting forever before its finite analysis run begins.
    timeoutId = window.setTimeout(() => complete(), 20 * 60 * 1000);
  });
}
