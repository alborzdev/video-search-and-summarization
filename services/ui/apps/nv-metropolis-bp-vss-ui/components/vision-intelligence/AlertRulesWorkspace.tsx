// SPDX-License-Identifier: MIT

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";
import { MonitoringRegionEditor } from './MonitoringRegionEditor';
import { LiveModeNav, type LiveMode } from './LiveModeNav';
import {
  loadAnalysisProfileCatalog,
  loadSourceAnalysisProfile,
  type SourceAnalysisProfile,
} from './analysisProfiles';
import {
  MONITORING_TEMPLATES,
  createMonitoringDraft,
  monitoringEngineLabel,
  monitoringRuleIsComplete,
  type MonitoringRule,
  type MonitoringRuleDraft,
  type MonitoringRuleKind,
  type MonitoringTemplate,
} from './monitoringRules';
import type { VisionStream } from './types';
import { isLiveStream, streamDisplayName } from './utils';
import { useVisionStreams } from './useVisionStreams';
import {
  IconAlertTriangle,
  IconBell,
  IconBellCog,
  IconBolt,
  IconBrain,
  IconClock,
  IconEye,
  IconPlus,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconRoute,
  IconShieldCheck,
  IconSparkles,
  IconTrash,
  IconX,
} from '@tabler/icons-react';
import React, { FormEvent, useCallback, useEffect, useState } from 'react';

interface AlertRulesWorkspaceProps {
  initialSourceId?: string | null;
  onManageSources: () => void;
  onModeChange?: (mode: Exclude<LiveMode, 'rules'>) => void;
  vstApiUrl?: string | null;
}

type WizardStep = 'condition' | 'region' | 'review';

function ruleStatusCopy(rule: MonitoringRule): string {
  if (rule.status === 'paused') return 'Paused';
  if (rule.backendStatus === 'unavailable') return 'Needs attention';
  if (rule.backendStatus === 'pending') return 'Applying locally';
  return 'Active';
}

function parseIntent(value: string): MonitoringRuleKind {
  if (/close|near|proximity|distance|forklift|vehicle.*person|person.*vehicle/i.test(value)) return 'proximity';
  if (/describe|visual|unsafe|unusual|custom|watch for/i.test(value)) return 'semantic';
  return 'area-entry';
}

function selectedTemplate(kind: MonitoringRuleKind): MonitoringTemplate {
  return MONITORING_TEMPLATES.find((template) => template.id === kind) ?? MONITORING_TEMPLATES[0];
}

export function MonitoringRuleWizard({
  analysisProfileId,
  onClose,
  onCreated,
  onManageSources,
  preselectedSourceId,
  streams,
  vstApiUrl,
}: {
  analysisProfileId?: string;
  onClose: () => void;
  onCreated: (rule: MonitoringRule) => void;
  onManageSources?: () => void;
  preselectedSourceId?: string | null;
  streams: VisionStream[];
  vstApiUrl?: string | null;
}) {
  const initialStream = streams.find((stream) => stream.streamId === preselectedSourceId || stream.sensorId === preselectedSourceId) ?? streams[0];
  const [streamId, setStreamId] = useState(initialStream?.streamId ?? '');
  const stream = streams.find((candidate) => candidate.streamId === streamId) ?? initialStream;
  const [intent, setIntent] = useState('Tell me when a person enters this area');
  const [draft, setDraft] = useState<MonitoringRuleDraft | null>(
    stream ? createMonitoringDraft(stream) : null,
  );
  const [step, setStep] = useState<WizardStep>('condition');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profileCatalog, setProfileCatalog] = useState<SourceAnalysisProfile[]>([]);
  const [profilesBySource, setProfilesBySource] = useState<Record<string, SourceAnalysisProfile>>({});

  const [profilesLoading, setProfilesLoading] = useState(true);

  const dialogRef = useDialogAccessibility<HTMLElement>({ isOpen: true, onClose });

  const profileForStream = useCallback((target?: VisionStream) => {
    if (!target) return undefined;
    // During a blocking upload the selected profile is supplied explicitly,
    // before the source has been committed to the agent's durable state. That
    // choice must win over a transient/default source lookup.
    return (analysisProfileId ? profileCatalog.find((profile) => profile.id === analysisProfileId) : undefined)
      ?? profilesBySource[target.sensorId]
      ?? profilesBySource[target.streamId]
      ?? undefined;
  }, [analysisProfileId, profileCatalog, profilesBySource]);

  useEffect(() => {
    const controller = new AbortController();
    setProfilesLoading(true);
    Promise.all([
      loadAnalysisProfileCatalog(controller.signal),
      Promise.all(streams.map(async (candidate) => {
        try {
          return [candidate.sensorId, await loadSourceAnalysisProfile(candidate.sensorId, controller.signal)] as const;
        } catch {
          return null;
        }
      })),
    ])
      .then(([catalog, sourceProfiles]) => {
        setProfileCatalog(catalog);
        setProfilesBySource(Object.fromEntries(sourceProfiles.filter((entry): entry is readonly [string, SourceAnalysisProfile] => entry !== null)));
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : 'Source analysis profiles are unavailable.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setProfilesLoading(false);
      });
    return () => controller.abort();
  }, [streams]);

  useEffect(() => {
    if (draft || !streams.length) return;
    const available = streams.find((candidate) => candidate.streamId === preselectedSourceId || candidate.sensorId === preselectedSourceId) ?? streams[0];
    setStreamId(available.streamId);
    setDraft(createMonitoringDraft(available));
  }, [draft, preselectedSourceId, streams]);

  useEffect(() => {
    const selectedStream = streams.find((candidate) => candidate.streamId === streamId) ?? initialStream;
    const selectedProfile = profileForStream(selectedStream);
    if (!selectedStream || !selectedProfile || draft?.analysisProfileId === selectedProfile.id) return;
    const compatible = MONITORING_TEMPLATES.find((candidate) =>
      (isLiveStream(selectedStream) || candidate.supportsRecorded)
      && (candidate.engine === 'vlm'
        ? isLiveStream(selectedStream)
        : selectedProfile.detectionEnabled && selectedProfile.ruleKinds.includes(candidate.id)),
    );
    if (compatible) setDraft(createMonitoringDraft(selectedStream, compatible, selectedProfile));
  }, [draft?.analysisProfileId, initialStream, profileForStream, streamId, streams]);

  const applyTemplate = (template: MonitoringTemplate, target = stream) => {
    if (!target) return;
    const next = createMonitoringDraft(target, template, profileForStream(target));
    setDraft((current) => current ? {
      ...next,
      cooldownSeconds: current.cooldownSeconds,
      notify: current.notify,
      severity: current.severity,
    } : next);
  };

  const chooseSource = (nextStreamId: string) => {
    setStreamId(nextStreamId);
    const next = streams.find((candidate) => candidate.streamId === nextStreamId);
    if (!next) return;
    const profile = profileForStream(next);
    const preferred = selectedTemplate(draft?.kind ?? 'area-entry');
    const templates = MONITORING_TEMPLATES.filter((candidate) =>
      (isLiveStream(next) || candidate.supportsRecorded)
      && (candidate.engine === 'vlm'
        ? isLiveStream(next)
        : Boolean(profile?.detectionEnabled && profile.ruleKinds.includes(candidate.id))),
    );
    const template = templates.find((candidate) => candidate.id === preferred.id) ?? templates[0];
    if (template) applyTemplate(template, next);
  };

  const advanceFromCondition = (event: FormEvent) => {
    event.preventDefault();
    if (!draft || !stream) return;
    const profile = profileForStream(stream);
    const templates = MONITORING_TEMPLATES.filter((candidate) =>
      (isLiveStream(stream) || candidate.supportsRecorded)
      && (candidate.engine === 'vlm'
        ? isLiveStream(stream)
        : Boolean(profile?.detectionEnabled && profile.ruleKinds.includes(candidate.id))),
    );
    const inferred = selectedTemplate(parseIntent(intent));
    const allowed = templates.find((candidate) => candidate.id === inferred.id) ?? templates[0];
    if (!allowed) {
      setError('This source is search-only. Choose a detector profile before creating a structured monitoring rule.');
      return;
    }
    applyTemplate(allowed);
    setStep(allowed.geometry === 'polygon' ? 'region' : 'review');
  };

  const createRule = async () => {
    if (!draft || !stream || !profileForStream(stream) || !monitoringRuleIsComplete(draft)) return;
    setSaving(true);
    setError(null);
    let liveRuleId = '';
    try {
      let requestDraft: MonitoringRuleDraft & { backendRuleId?: string } = draft;
      if (draft.engine === 'vlm') {
        const bridgeResponse = await fetch('/api/vision/live-alert-rules', {
          body: JSON.stringify({
            alert_type: draft.kind,
            live_stream_url: stream.url,
            prompt: draft.prompt,
            sensor_id: stream.sensorId,
            sensor_name: stream.name,
          }),
          headers: { 'Content-Type': 'application/json' },
          method: 'POST',
        });
        const bridgePayload = await bridgeResponse.json() as { error?: string; id?: string; message?: string };
        if (!bridgeResponse.ok || !bridgePayload.id) {
          throw new Error(bridgePayload.error || bridgePayload.message || 'The visual rule could not be started.');
        }
        liveRuleId = bridgePayload.id;
        requestDraft = { ...draft, backendRuleId: liveRuleId };
      }
      const response = await fetch('/api/vision/monitoring-rules', {
        body: JSON.stringify(requestDraft),
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
      });
      const payload = await response.json() as { error?: string; rule?: MonitoringRule };
      if (!response.ok || !payload.rule) throw new Error(payload.error || 'The rule could not be saved.');
      onCreated(payload.rule);
    } catch (requestError) {
      if (liveRuleId) {
        await fetch(`/api/vision/live-alert-rules?id=${encodeURIComponent(liveRuleId)}`, { method: 'DELETE' }).catch(() => undefined);
      }
      setError(requestError instanceof Error ? requestError.message : 'The rule could not be created.');
    } finally {
      setSaving(false);
    }
  };

  if (!stream || !draft) {
    return (
      <div className="vi-rule-wizard-backdrop" role="presentation">
        <section ref={dialogRef} className="vi-rule-wizard vi-rule-wizard-empty" role="dialog" aria-modal="true" aria-labelledby="vi-rule-wizard-title">
          <header><div><span>New monitoring rule</span><h2 id="vi-rule-wizard-title">Connect a source first</h2></div><button type="button" onClick={onClose} aria-label="Close rule builder"><IconX size={20} /></button></header>
          <div><IconBellCog size={28} /><p>A live camera or recorded video is needed before Thor can monitor a condition.</p><button className="is-primary" type="button" onClick={() => { onClose(); onManageSources?.(); }}>Back to sources</button></div>
        </section>
      </div>
    );
  }
  const template = selectedTemplate(draft.kind);
  const analysisProfile = profileForStream(stream);
  const compatibleTemplates = MONITORING_TEMPLATES.filter((candidate) =>
    (isLiveStream(stream) || candidate.supportsRecorded)
    && (candidate.engine === 'vlm'
      ? isLiveStream(stream)
      : Boolean(analysisProfile?.detectionEnabled && analysisProfile.ruleKinds.includes(candidate.id))),
  );
  const stepNumber = step === 'condition' ? 1 : step === 'region' ? 2 : template.geometry === 'polygon' ? 3 : 2;

  return (
    <div className="vi-rule-wizard-backdrop" role="presentation">
      <section ref={dialogRef} className="vi-rule-wizard" role="dialog" aria-modal="true" aria-labelledby="vi-rule-wizard-title">
        <header>
          <div>
            <span>New monitoring rule</span>
            <h2 id="vi-rule-wizard-title">
              {step === 'condition' ? 'What should Thor watch for?' : step === 'region' ? 'Draw the monitored area' : 'Review and activate'}
            </h2>
          </div>
          <div className="vi-rule-wizard-progress" aria-label={`Step ${stepNumber}`}>
            {[1, 2, ...(template.geometry === 'polygon' ? [3] : [])].map((value) => <i className={value <= stepNumber ? 'is-active' : ''} key={value} />)}
          </div>
          <button type="button" onClick={onClose} aria-label="Close rule builder"><IconX size={20} /></button>
        </header>

        {step === 'condition' && (
          <form className="vi-rule-intent" onSubmit={advanceFromCondition}>
            <label>
              <span>Source</span>
              <select aria-label="Monitoring source" value={streamId} onChange={(event) => chooseSource(event.target.value)}>
                {streams.map((candidate) => (
                  <option key={candidate.streamId} value={candidate.streamId}>
                    {streamDisplayName(candidate.name)} · {isLiveStream(candidate) ? 'Live' : 'Recorded'}
                  </option>
                ))}
              </select>
            </label>
            <label className="vi-rule-natural-language">
              <span>Describe what matters</span>
              <div><IconSparkles size={20} /><input aria-label="Monitoring intent" value={intent} onChange={(event) => setIntent(event.target.value)} /></div>
            </label>
            <div className="vi-rule-recorded-note">
              <IconBolt size={17} />
              <span>
                {profilesLoading
                  ? 'Checking this source’s installed analytics profile…'
                  : analysisProfile
                    ? `${analysisProfile.name} · ${analysisProfile.modelLabel}`
                    : 'The selected source profile could not be verified.'}
              </span>
            </div>
            <div className="vi-rule-template-grid">
              {compatibleTemplates.map((candidate) => {
                const Icon = candidate.engine === 'vlm' ? IconBrain : candidate.id === 'proximity' ? IconRoute : IconShieldCheck;
                return (
                  <button
                    className={draft.kind === candidate.id ? 'is-selected' : ''}
                    key={candidate.id}
                    onClick={() => {
                      applyTemplate(candidate);
                      setIntent(candidate.id === 'area-entry' ? 'Tell me when a person enters this area' : candidate.id === 'proximity' ? 'Tell me when selected objects are too close' : candidate.prompt ?? '');
                    }}
                    type="button"
                  >
                    <Icon size={22} />
                    <strong>{candidate.label}</strong>
                    <span>{candidate.description}</span>
                    <em>{monitoringEngineLabel(candidate.engine)}</em>
                  </button>
                );
              })}
            </div>
            {!profilesLoading && compatibleTemplates.length === 0 && (
              <div className="vi-rule-error">
                <IconAlertTriangle size={17} /> Search-only recordings do not publish object tracks. Reprocess this source with a compatible detector profile to add area or proximity rules.
              </div>
            )}
            {!isLiveStream(stream) && (
              <div className="vi-rule-recorded-note"><IconClock size={17} /><span>Recorded rules evaluate while the file is processed. Results appear as historical incidents on its timeline.</span></div>
            )}
            <footer><button type="button" onClick={onClose}>Skip for now</button><button className="is-primary" type="submit">Continue <span>→</span></button></footer>
          </form>
        )}

        {step === 'region' && (
          <div className="vi-rule-region-step">
            <div className="vi-rule-region-instruction">
              <IconShieldCheck size={20} />
              <div><strong>Mark the area that matters</strong><span>Click around its boundary. Drag any point to refine it. Coordinates stay attached to this source.</span></div>
            </div>
            <MonitoringRegionEditor geometry={draft.geometry} onChange={(geometry) => setDraft({ ...draft, geometry })} stream={stream} vstApiUrl={vstApiUrl} />
            <footer><button type="button" onClick={() => setStep('condition')}>Back</button><button className="is-primary" type="button" disabled={draft.geometry.points.length < 3} onClick={() => setStep('review')}>Review rule <span>→</span></button></footer>
          </div>
        )}

        {step === 'review' && (
          <div className="vi-rule-review">
            <div className="vi-rule-review-summary">
              <span className={`is-${draft.engine}`}><IconBolt size={16} /> {monitoringEngineLabel(draft.engine)}</span>
              <h3>{streamDisplayName(stream.name)}</h3>
              <p>{draft.engine === 'deepstream' ? 'The installed detector tracks objects and Behavior Analytics creates incidents when this rule is satisfied.' : 'Cosmos Reason continuously verifies this visual condition. Thor can focus on one continuous visual rule at a time.'}</p>
            </div>
            <div className="vi-rule-review-fields">
              <label><span>Rule name</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
              {draft.engine === 'deepstream' ? (
                <fieldset>
                  <legend>Objects to monitor</legend>
                  {(analysisProfile?.objectTypes ?? []).map((objectType) => (
                    <label key={objectType}><input type="checkbox" checked={draft.objectTypes.includes(objectType)} onChange={() => setDraft({ ...draft, objectTypes: draft.objectTypes.includes(objectType) ? draft.objectTypes.filter((item) => item !== objectType) : [...draft.objectTypes, objectType] })} /> {objectType}</label>
                  ))}
                </fieldset>
              ) : (
                <label><span>Visual condition</span><textarea value={draft.prompt ?? ''} onChange={(event) => setDraft({ ...draft, prompt: event.target.value })} /></label>
              )}
              {draft.kind === 'proximity' && <label><span>Image-space proximity</span><div className="vi-rule-inline-input"><input min="40" max="400" step="10" type="number" value={draft.threshold.proximityPixels ?? 140} onChange={(event) => setDraft({ ...draft, threshold: { ...draft.threshold, proximityPixels: Number(event.target.value) } })} /><em>pixels</em></div><small>Uses distance in this camera view. World-space metres require a calibrated floor plan.</small></label>}
              <label><span>Severity</span><select value={draft.severity} onChange={(event) => setDraft({ ...draft, severity: event.target.value as MonitoringRuleDraft['severity'] })}><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Information</option></select></label>
              <label><span>Repeat cooldown</span><select value={draft.cooldownSeconds} onChange={(event) => setDraft({ ...draft, cooldownSeconds: Number(event.target.value) })}><option value={15}>15 seconds</option><option value={30}>30 seconds</option><option value={60}>1 minute</option><option value={300}>5 minutes</option></select></label>
              <div className="vi-rule-notify"><IconBell size={17} /><span><strong>Quiet in-app notification</strong><small>Matches appear in Activity and Needs attention. External notifications stay off unless an administrator configures them.</small></span></div>
            </div>
            {error && <div className="vi-rule-error"><IconAlertTriangle size={17} /> {error}</div>}
            <footer><button type="button" onClick={() => setStep(template.geometry === 'polygon' ? 'region' : 'condition')}>Back</button><button className="is-primary" type="button" disabled={saving || !analysisProfile || !monitoringRuleIsComplete(draft)} onClick={() => void createRule()}>{saving ? <><span className="vi-spinner" /> Activating locally…</> : <><IconBell size={17} /> Activate monitoring</>}</button></footer>
          </div>
        )}
      </section>
    </div>
  );
}

export function AlertRulesWorkspace({ initialSourceId, onManageSources, onModeChange, vstApiUrl }: AlertRulesWorkspaceProps) {
  const { streams } = useVisionStreams(vstApiUrl);
  const [rules, setRules] = useState<MonitoringRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [wizardSourceId, setWizardSourceId] = useState<string | null>(initialSourceId ?? null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/vision/monitoring-rules', { cache: 'no-store' });
      const payload = await response.json() as { error?: string; rules?: MonitoringRule[] };
      if (!response.ok) throw new Error(payload.error || 'Monitoring rules are unavailable.');
      setRules(payload.rules ?? []);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Monitoring rules are unavailable.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!initialSourceId) return;
    setWizardSourceId(initialSourceId);
    setShowWizard(true);
  }, [initialSourceId]);

  const activeCount = rules.filter((rule) => rule.status === 'active').length;
  const sourceCount = new Set(rules.map((rule) => rule.sourceId)).size;

  const updateState = async (rule: MonitoringRule, action: 'pause' | 'resume') => {
    setError(null);
    try {
      const response = await fetch(`/api/vision/monitoring-rules?id=${encodeURIComponent(rule.id)}`, {
        body: JSON.stringify({ action }),
        headers: { 'Content-Type': 'application/json' },
        method: 'PATCH',
      });
      const payload = await response.json() as { error?: string; rule?: MonitoringRule };
      if (!response.ok || !payload.rule) throw new Error(payload.error || 'The rule could not be updated.');
      setRules((current) => current.map((candidate) => candidate.id === rule.id ? payload.rule! : candidate));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The rule could not be updated.');
    }
  };

  const deleteRule = async (rule: MonitoringRule) => {
    setError(null);
    try {
      if (rule.engine === 'vlm' && rule.backendRuleId) {
        const bridgeResponse = await fetch(`/api/vision/live-alert-rules?id=${encodeURIComponent(rule.backendRuleId)}`, { method: 'DELETE' });
        if (!bridgeResponse.ok && bridgeResponse.status !== 404) {
          const bridgePayload = await bridgeResponse.json().catch(() => ({})) as { error?: string };
          throw new Error(bridgePayload.error || 'The continuous visual rule could not be stopped.');
        }
      }
      const response = await fetch(`/api/vision/monitoring-rules?id=${encodeURIComponent(rule.id)}`, { method: 'DELETE' });
      const payload = await response.json().catch(() => ({})) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'The rule could not be deleted.');
      setRules((current) => current.filter((candidate) => candidate.id !== rule.id));
      setPendingDelete(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The rule could not be deleted.');
    }
  };

  return (
    <section className="vi-monitoring-workspace">
      {onModeChange && (
        <LiveModeNav
          active="rules"
          onSelect={(mode) => {
            if (mode !== 'rules') onModeChange(mode);
          }}
        />
      )}
      <div className="vi-monitoring-content">
        <div className="vi-monitoring-heading">
          <div><span className="vi-eyebrow">Local rules · actionable incidents</span><h1>Rules</h1><p>Tell Thor what matters. Detection rules scale across sources; one continuous visual rule can handle a condition that needs scene reasoning.</p></div>
          <button type="button" onClick={() => { setWizardSourceId(null); setShowWizard(true); }}><IconPlus size={18} /> New monitoring rule</button>
        </div>
        <div className="vi-monitoring-summary">
          <div><IconEye size={19} /><span><strong>{activeCount}</strong> active {activeCount === 1 ? 'rule' : 'rules'}</span></div>
          <div><IconShieldCheck size={19} /><span><strong>{sourceCount}</strong> monitored {sourceCount === 1 ? 'source' : 'sources'}</span></div>
          <div><IconBrain size={19} /><span><strong>{rules.filter((rule) => rule.engine === 'vlm' && rule.status === 'active').length}/1</strong> visual reasoning slot</span></div>
          <button type="button" onClick={() => void refresh()}><IconRefresh size={16} /> Refresh</button>
        </div>
        {error && <div className="vi-rule-error"><IconAlertTriangle size={17} /> {error}</div>}
        <div className="vi-monitoring-list-heading"><div><h2>Rules by source</h2><span>Only rule matches become incidents. Raw detections stay out of Activity.</span></div><button type="button" onClick={onManageSources}>Manage sources</button></div>
        <div className="vi-monitoring-list">
          {loading && !rules.length ? <div className="vi-monitoring-empty"><span className="vi-spinner" /> Loading local rules…</div> : rules.length ? rules.map((rule) => (
            <article key={rule.id}>
              <div className={`vi-monitoring-rule-icon is-${rule.engine}`}>{rule.engine === 'vlm' ? <IconBrain size={21} /> : <IconShieldCheck size={21} />}</div>
              <div className="vi-monitoring-rule-copy"><div><span className={`vi-monitoring-status is-${rule.status}`}>{ruleStatusCopy(rule)}</span><em>{rule.severity}</em></div><h3>{rule.name}</h3><p>{rule.description}</p><small>{rule.sourceName} · {rule.sourceKind === 'live' ? 'Continuous' : 'Recorded run'} · {monitoringEngineLabel(rule.engine)} · {rule.cooldownSeconds}s cooldown</small></div>
              <div className="vi-monitoring-rule-actions">
                {rule.engine === 'deepstream' && <button type="button" onClick={() => void updateState(rule, rule.status === 'active' ? 'pause' : 'resume')}>{rule.status === 'active' ? <><IconPlayerPause size={17} /> Pause</> : <><IconPlayerPlay size={17} /> Resume</>}</button>}
                {pendingDelete === rule.id ? <div><button className="is-danger" type="button" onClick={() => void deleteRule(rule)}>Delete rule</button><button type="button" onClick={() => setPendingDelete(null)}>Cancel</button></div> : <button type="button" aria-label={`Delete ${rule.name}`} onClick={() => setPendingDelete(rule.id)}><IconTrash size={17} /></button>}
              </div>
            </article>
          )) : <div className="vi-monitoring-empty"><IconBellCog size={25} /><strong>No monitoring rules yet</strong><span>Create one in plain language, then draw an area only when the condition needs it.</span><button type="button" onClick={() => setShowWizard(true)}>Create first rule</button></div>}
        </div>
      </div>
      {showWizard && <MonitoringRuleWizard onClose={() => setShowWizard(false)} onCreated={(rule) => { setRules((current) => [...current, rule]); setShowWizard(false); }} onManageSources={onManageSources} preselectedSourceId={wizardSourceId} streams={streams} vstApiUrl={vstApiUrl} />}
    </section>
  );
}
