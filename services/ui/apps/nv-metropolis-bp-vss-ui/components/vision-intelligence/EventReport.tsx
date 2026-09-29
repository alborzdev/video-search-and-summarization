// SPDX-License-Identifier: MIT
import React, { useState } from "react";
import { incidentTitle, incidentVerdictLabel, type AnalyticsIncident } from "./incidentModel";
import type { MonitoringRule } from "./monitoringRules";
import type { InvestigationCreateRequest, InvestigationRecord } from "./investigation";

type EventContext = { incident: AnalyticsIncident; rule: MonitoringRule | null; sensorId: string; sourceName: string };

export function eventReportRequest(context: EventContext, title: string, notes: string): InvestigationCreateRequest {
  const { incident, rule, sensorId, sourceName } = context;
  if (!sensorId || !incident.end || !Number.isFinite(Date.parse(incident.timestamp)) ||
      !Number.isFinite(Date.parse(incident.end)) || Date.parse(incident.end) <= Date.parse(incident.timestamp)) {
    throw new Error("A source and valid event interval are required to save evidence.");
  }
  const name = rule?.name || incidentTitle(incident);
  const query = incident.info?.prompt?.trim() || rule?.prompt || name;
  const summary = `Event “${name}” was recorded with status “${incidentVerdictLabel(incident)}”. This report preserves the event record; no new AI analysis was run. Event ID: ${incident.Id}.`;
  const clientId = `event:${incident.Id}`;
  const interval = { start_time: incident.timestamp, end_time: incident.end, source_name: sourceName };
  return {
    title: title.trim() || `Event review — ${name}`, notes, query,
    disposition: "under_review",
    severity: rule?.severity === "critical" ? "critical" : rule?.severity === "warning" ? "medium" : "low",
    evidence: [{ ...interval, client_id: clientId, sensor_id: sensorId, image_url: "", match_type: "Event interval", title: name }],
    analysis: {
      status: "complete", query, question: query, summary,
      observations: [{ text: summary, evidence_ids: ["E1"] }], interpretations: [], suggested_questions: [],
      evidence: [{ ...interval, client_id: clientId, evidence_id: "E1", match_type: "Event interval", inspection_source: "retained_event_record", observation: summary }],
      timeline: [{ ...interval, evidence_id: "E1", label: "Recorded event interval" }],
    },
  };
}

export function EventReport({ onSaved, ...context }: EventContext & { onSaved?: (record: InvestigationRecord) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(`Event review — ${context.rule?.name || incidentTitle(context.incident)}`);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [record, setRecord] = useState<InvestigationRecord | null>(null);
  if (record) return <div className="vi-live-report" role="status">
    <strong>Event report saved</strong>
    <p>{record.evidence.every(item => item.media_status === "retained") ? "The event clip is cached locally with this report." : "The event and notes are saved. Video still depends on source retention."}</p>
    <a className="vi-analyst-investigate" href={record.report_url}>Open event report</a>
  </div>;
  if (!open) return <button className="vi-analyst-investigate" type="button" onClick={() => setOpen(true)}>Save event report</button>;
  return <form className="vi-live-report" aria-label="Save event report" onSubmit={async event => {
    event.preventDefault(); if (saving) return;
    setSaving(true); setError(null);
    try {
      const response = await fetch("/api/vision/investigations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(eventReportRequest(context, title, notes)) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The event report could not be saved.");
      setRecord(payload as InvestigationRecord);
      onSaved?.(payload as InvestigationRecord);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The event report could not be saved."); }
    finally { setSaving(false); }
  }}>
    <label>Report title<input aria-label="Event report title" value={title} maxLength={500} disabled={saving} onChange={event => setTitle(event.target.value)} /></label>
    <label>Review notes<textarea aria-label="Event report notes" value={notes} maxLength={5000} disabled={saving} onChange={event => setNotes(event.target.value)} placeholder="What did you observe in the event footage?" /></label>
    <p>Saves the event, exact video interval and your notes for review. No new AI analysis is run.</p>
    {error && <p role="alert">{error}</p>}
    <div><button className="vi-analyst-investigate" type="submit" disabled={saving}>{saving ? "Saving event and clip…" : "Save report with evidence"}</button>
    <button className="vi-analyst-investigate" type="button" disabled={saving} onClick={() => setOpen(false)}>Cancel</button></div>
  </form>;
}
