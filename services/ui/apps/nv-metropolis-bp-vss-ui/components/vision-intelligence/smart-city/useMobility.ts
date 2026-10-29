// SPDX-License-Identifier: MIT
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CitySite } from './types';
import type { MobilityConfigInput, MobilityConfigResponse, MobilityReport, MobilityWindow } from './mobilityTypes';
import { cityRequest } from './useCity';
import { useDocumentVisible } from './useDocumentVisible';

export function mobilityReportMatches(value: MobilityReport, site: Pick<CitySite, 'id' | 'revision' | 'mode'>, windowMinutes: MobilityWindow): boolean {
  return Boolean(value && value.schemaVersion === 'city.mobility.v1' && value.siteId === site.id && value.siteRevision === site.revision && value.mode === site.mode && value.windowMinutes === windowMinutes &&
    value.timeBasis === 'per-camera-source-time' && value.globalFusionEnabled === false && Number.isInteger(value.configRevision) && value.config && value.config.revision === value.configRevision &&
    (value.curbs === undefined || Array.isArray(value.curbs)) && (value.config.curbs === undefined || Array.isArray(value.config.curbs)) &&
    [value.coverage, value.lineCounts, value.movements, value.obstructions, value.queues, value.crossings, value.configurationIssues, value.limitations, value.config.movements, value.config.crossings, value.config.queues].every(Array.isArray));
}

/** One bounded request at a time. A hidden tab does not poll or retain a pending save. */
export function useMobility(site: CitySite) {
  const visible = useDocumentVisible();
  const [windowMinutes, setWindowMinutes] = useState<MobilityWindow>(5);
  const [refreshToken, setRefreshToken] = useState(0);
  const context = JSON.stringify([site.id, site.revision, site.mode, site.sources.map(source => source.id)]);
  const key = `${context}:${windowMinutes}`;
  const [record, setRecord] = useState<{ key: string; value: MobilityReport; receivedAt: string } | null>(null);
  const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false);
  const saveController = useRef<AbortController | null>(null); const saveGeneration = useRef(0);
  useEffect(() => {
    ++saveGeneration.current; saveController.current?.abort('context-changed'); saveController.current = null; setSaving(false);
    return () => { ++saveGeneration.current; saveController.current?.abort('unmounted'); saveController.current = null; };
  }, [context, visible]);
  useEffect(() => {
    setRecord(null); setError(null); setLoading(visible);
    if (!visible) return;
    let active = true; let timer: ReturnType<typeof setTimeout> | null = null; let controller: AbortController | null = null;
    const poll = async () => {
      const pending = new AbortController(); controller = pending;
      const timeout = setTimeout(() => pending.abort('timeout'), 8000);
      try {
        const value = await cityRequest<MobilityReport>(`mobility?windowMinutes=${windowMinutes}`, { signal: pending.signal });
        if (!active || pending.signal.aborted) return;
        if (!mobilityReportMatches(value, site, windowMinutes)) throw new Error('Insights do not match the current site or report window. Refresh the city configuration.');
        setRecord({ key, value, receivedAt: new Date().toISOString() }); setError(null);
      } catch (cause) {
        if (active && (!pending.signal.aborted || pending.signal.reason === 'timeout')) setError(pending.signal.reason === 'timeout' ? 'Insights request timed out. Retrying shortly.' : cause instanceof Error ? cause.message : 'Insights are unavailable.');
      } finally { clearTimeout(timeout); if (active) { setLoading(false); timer = setTimeout(() => void poll(), 3000); } }
    };
    void poll();
    return () => { active = false; controller?.abort('refresh'); if (timer !== null) clearTimeout(timer); };
  }, [key, visible, refreshToken]); // key includes site identity, source configuration and window.
  const refresh = useCallback(() => {
    ++saveGeneration.current; saveController.current?.abort('refresh'); saveController.current = null; setSaving(false); setRefreshToken(value => value + 1);
  }, []);
  const saveConfig = useCallback(async (value: MobilityConfigInput): Promise<MobilityConfigResponse> => {
    if (saveController.current) throw new Error('A settings save is already in progress.');
    const controller = new AbortController(); saveController.current = controller; const generation = ++saveGeneration.current; setSaving(true);
    const timeout = setTimeout(() => controller.abort('timeout'), 10000);
    try {
      const result = await cityRequest<MobilityConfigResponse>('mobility/config', { method: 'PUT', signal: controller.signal, body: JSON.stringify(value) });
      if (controller.signal.aborted || generation !== saveGeneration.current) throw new DOMException('Settings save was cancelled. Refresh to check the stored revision.', 'AbortError');
      if (!result?.config || result.config.revision !== result.configRevision || !Number.isInteger(result.configRevision)) throw new Error('The service did not confirm the saved settings revision. Refresh before trying again.');
      setRefreshToken(token => token + 1); return result;
    } catch (cause) {
      if (controller.signal.reason === 'timeout') throw new Error('Settings save timed out. Refresh to check whether it was stored before retrying.');
      throw cause;
    } finally { clearTimeout(timeout); if (generation === saveGeneration.current) { saveController.current = null; setSaving(false); } }
  }, []);
  const current = record?.key === key ? record : null;
  return { report: current?.value ?? null, receivedAt: current?.receivedAt ?? null, error, loading, saving, windowMinutes, setWindowMinutes, refresh, saveConfig };
}
