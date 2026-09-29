// SPDX-License-Identifier: MIT
import React, { useState } from "react";
import type { VisionAnalystRequest, VisionAnalystResponse } from "./analyst";
import type { InvestigationCreateRequest, InvestigationRecord } from "./investigation";
import { streamDisplayName } from "./utils";

type AnswerSource = VisionAnalystRequest["sources"][number];

export function liveAnswerReportRequest(
  result: VisionAnalystResponse, source: AnswerSource, title: string, notes: string,
): InvestigationCreateRequest {
  const window = result.observedWindow;
  if (!window || !Number.isFinite(Date.parse(window.startTime)) ||
      !Number.isFinite(Date.parse(window.endTime)) || Date.parse(window.endTime) <= Date.parse(window.startTime)) {
    throw new Error("The answer has no valid inspected interval to save.");
  }
  const clientId = `${source.sensorId}:${window.startTime}:${window.endTime}`;
  return {
    title: title.trim() || `Camera review — ${streamDisplayName(source.name)}`,
    notes, disposition: "under_review", severity: "low", query: result.query,
    evidence: [{
      client_id: clientId, sensor_id: source.sensorId, source_name: source.name,
      start_time: window.startTime, end_time: window.endTime, image_url: "",
      match_type: "Fresh visual inspection", title: result.query,
    }],
    analysis: {
      status: "complete", query: result.query, question: result.query, summary: result.answer,
      observations: [{text: result.answer, evidence_ids: ["E1"]}], interpretations: [], suggested_questions: [],
      evidence: [{client_id: clientId, evidence_id: "E1", start_time: window.startTime,
        end_time: window.endTime, source_name: source.name, match_type: "Fresh visual inspection",
        inspection_source: "fresh_cosmos_inspection", observation: result.answer}],
      timeline: [{evidence_id: "E1", start_time: window.startTime, end_time: window.endTime,
        source_name: source.name, label: "Inspected RTSP interval"}],
    },
  };
}

export function LiveAnswerReport({result, source}: {result: VisionAnalystResponse; source: AnswerSource}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(`Camera review — ${streamDisplayName(source.name)}`);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [record, setRecord] = useState<InvestigationRecord | null>(null);
  if (record) return <div className="vi-live-report" role="status">
    <strong>Report saved for review</strong>
    <p>{record.evidence.every(item => item.media_status === "retained")
      ? "The inspected clip is cached locally with this report."
      : "The answer and timestamps are saved. Video still depends on source retention."}</p>
    <a className="vi-analyst-investigate" href={record.report_url}>Open report</a>
  </div>;
  if (!open) return <button className="vi-analyst-investigate" type="button" onClick={() => setOpen(true)}>Save report</button>;
  return <form className="vi-live-report" aria-label="Save live answer report" onSubmit={async event => {
    event.preventDefault();
    if (saving) return;
    setSaving(true); setError(null);
    try {
      const response = await fetch("/api/vision/investigations", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(liveAnswerReportRequest(result, source, title, notes)),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The report could not be saved.");
      setRecord(payload as InvestigationRecord);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The report could not be saved.");
    } finally { setSaving(false); }
  }}>
    <label>Report title<input aria-label="Live report title" value={title} maxLength={500} onChange={event => setTitle(event.target.value)} disabled={saving} /></label>
    <label>Review notes<textarea aria-label="Live report notes" value={notes} maxLength={5000} onChange={event => setNotes(event.target.value)} disabled={saving} placeholder="What did you confirm in the inspected clip?" /></label>
    <p>Saves this AI answer and its exact interval for review. Check the clip before endorsing the answer.</p>
    {error && <p role="alert">{error}</p>}
    <div><button className="vi-analyst-investigate" type="submit" disabled={saving}>{saving ? "Saving report and clip…" : "Save report with evidence"}</button>
    <button className="vi-analyst-investigate" type="button" disabled={saving} onClick={() => setOpen(false)}>Cancel</button></div>
  </form>;
}
