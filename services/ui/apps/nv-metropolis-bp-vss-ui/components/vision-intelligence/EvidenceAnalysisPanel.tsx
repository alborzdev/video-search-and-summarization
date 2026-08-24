// SPDX-License-Identifier: MIT

import type {
  EvidenceAnalysisClaim,
  EvidenceAnalysisResponse,
} from "./evidenceAnalysis";
import type {
  InvestigationCreateRequest,
  InvestigationDisposition,
  InvestigationRecord,
  InvestigationSeverity,
} from "./investigation";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconCheck,
  IconClock,
  IconDownload,
  IconFileReport,
  IconMessageCircle,
  IconPlayerPlay,
  IconShieldCheck,
  IconSparkles,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import React, { FormEvent, useState } from "react";

export interface SelectedEvidenceItem {
  clientId: string;
  endTime: string;
  imageUrl: string;
  matchType: string;
  sensorId: string;
  sourceName: string;
  startTime: string;
  title: string;
}

interface EvidenceAnalysisPanelProps {
  analysis: EvidenceAnalysisResponse | null;
  error: string | null;
  isAnalyzing: boolean;
  items: SelectedEvidenceItem[];
  onAnalyze: () => void;
  onAsk: (question: string) => void;
  onClear: () => void;
  onOpenEvidence: (clientId: string) => void;
  onRemove: (clientId: string) => void;
}

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function CitationButtons({
  evidenceIds,
  evidenceById,
  onOpenEvidence,
}: {
  evidenceById: Map<string, string>;
  evidenceIds: string[];
  onOpenEvidence: (clientId: string) => void;
}) {
  return (
    <span className="vi-analysis-citations" aria-label="Supporting evidence">
      {evidenceIds.map((evidenceId) => {
        const clientId = evidenceById.get(evidenceId);
        return (
          <button
            type="button"
            key={evidenceId}
            disabled={!clientId}
            onClick={() => clientId && onOpenEvidence(clientId)}
          >
            {evidenceId}
          </button>
        );
      })}
    </span>
  );
}

function ClaimList({
  claims,
  evidenceById,
  onOpenEvidence,
}: {
  claims: EvidenceAnalysisClaim[];
  evidenceById: Map<string, string>;
  onOpenEvidence: (clientId: string) => void;
}) {
  return (
    <ul>
      {claims.map((claim, index) => (
        <li key={`${claim.text}-${index}`}>
          <span>{claim.text}</span>
          <CitationButtons
            evidenceById={evidenceById}
            evidenceIds={claim.evidence_ids}
            onOpenEvidence={onOpenEvidence}
          />
        </li>
      ))}
    </ul>
  );
}

export function EvidenceAnalysisPanel({
  analysis,
  error,
  isAnalyzing,
  items,
  onAnalyze,
  onAsk,
  onClear,
  onOpenEvidence,
  onRemove,
}: EvidenceAnalysisPanelProps) {
  const [question, setQuestion] = useState("");
  const [showInvestigationForm, setShowInvestigationForm] = useState(false);
  const [investigationTitle, setInvestigationTitle] = useState("");
  const [investigationSeverity, setInvestigationSeverity] =
    useState<InvestigationSeverity>("medium");
  const [investigationDisposition, setInvestigationDisposition] =
    useState<InvestigationDisposition>("open");
  const [investigationNotes, setInvestigationNotes] = useState("");
  const [investigationSaving, setInvestigationSaving] = useState(false);
  const [investigationError, setInvestigationError] = useState<string | null>(
    null
  );
  const [investigation, setInvestigation] =
    useState<InvestigationRecord | null>(null);
  const evidenceById = new Map(
    analysis?.evidence.map((item) => [item.evidence_id, item.client_id]) ?? []
  );
  const retainedCaptionCount =
    analysis?.evidence.filter(
      (item) => item.inspection_source === "retained_cosmos_caption"
    ).length ?? 0;
  const freshInspectionCount =
    analysis?.evidence.filter(
      (item) => item.inspection_source === "fresh_cosmos_inspection"
    ).length ?? 0;
  const submitQuestion = (event: FormEvent) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || isAnalyzing) return;
    onAsk(nextQuestion);
    setQuestion("");
  };
  const createInvestigation = async (event: FormEvent) => {
    event.preventDefault();
    if (!analysis || investigationSaving) return;
    const request: InvestigationCreateRequest = {
      analysis,
      disposition: investigationDisposition,
      evidence: items.map((item) => ({
        client_id: item.clientId,
        end_time: item.endTime,
        image_url: item.imageUrl,
        match_type: item.matchType,
        sensor_id: item.sensorId,
        source_name: item.sourceName,
        start_time: item.startTime,
        title: item.title,
      })),
      notes: investigationNotes,
      query: analysis.query,
      severity: investigationSeverity,
      title: investigationTitle.trim() || analysis.summary.slice(0, 180),
    };
    setInvestigationSaving(true);
    setInvestigationError(null);
    try {
      const response = await fetch("/api/vision/investigations", {
        body: JSON.stringify(request),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      const payload = (await response.json()) as InvestigationRecord & {
        error?: string;
      };
      if (!response.ok) {
        throw new Error(
          payload.error || `Investigation returned ${response.status}.`
        );
      }
      setInvestigation(payload);
      setShowInvestigationForm(false);
    } catch (saveError) {
      setInvestigationError(
        saveError instanceof Error
          ? saveError.message
          : "The investigation could not be saved."
      );
    } finally {
      setInvestigationSaving(false);
    }
  };

  return (
    <section
      className="vi-evidence-workspace"
      aria-label="Selected evidence workspace"
    >
      <header className="vi-evidence-workspace-header">
        <div>
          <span>
            <IconSparkles size={16} /> Evidence workspace
          </span>
          <strong>
            {items.length} selected clip{items.length === 1 ? "" : "s"}
          </strong>
        </div>
        <div>
          <button type="button" className="vi-evidence-clear" onClick={onClear}>
            <IconTrash size={15} /> Clear
          </button>
          <button
            type="button"
            className="vi-evidence-analyze"
            disabled={isAnalyzing}
            onClick={onAnalyze}
          >
            {isAnalyzing ? (
              <span className="vi-spinner" />
            ) : (
              <IconSparkles size={16} />
            )}
            {isAnalyzing
              ? `Inspecting ${items.length} clip${
                  items.length === 1 ? "" : "s"
                }…`
              : analysis
              ? "Analyze again"
              : "Analyze selected evidence"}
          </button>
        </div>
      </header>

      <div className="vi-evidence-tray">
        {items.map((item, index) => (
          <article key={item.clientId}>
            <button
              type="button"
              className="vi-evidence-tray-preview"
              onClick={() => onOpenEvidence(item.clientId)}
              aria-label={`Play evidence ${index + 1}: ${item.title}`}
            >
              <img src={item.imageUrl} alt="" />
              <span>
                <IconPlayerPlay size={12} /> E{index + 1}
              </span>
            </button>
            <div>
              <strong>{item.title}</strong>
              <span>
                {item.sourceName} · {formatClock(item.startTime)}
              </span>
              <small>{item.matchType}</small>
            </div>
            <button
              type="button"
              className="vi-evidence-tray-remove"
              onClick={() => onRemove(item.clientId)}
              aria-label={`Remove evidence ${index + 1}`}
            >
              <IconX size={15} />
            </button>
          </article>
        ))}
      </div>

      {error && (
        <div className="vi-evidence-analysis-error" role="alert">
          <IconAlertTriangle size={17} />
          <span>{error}</span>
          <button type="button" onClick={onAnalyze} disabled={isAnalyzing}>
            Try again
          </button>
        </div>
      )}

      {isAnalyzing && !analysis && (
        <div className="vi-evidence-analysis-loading" aria-live="polite">
          <span className="vi-spinner" />
          <div>
            <strong>Inspecting the actual selected footage</strong>
            <span>
              Local vision analyzes each clip before the evidence is
              synthesized. This can take a moment on Thor.
            </span>
          </div>
        </div>
      )}

      {analysis && (
        <div className="vi-evidence-analysis" aria-live="polite">
          <section className="vi-evidence-answer">
            <span>
              <IconSparkles size={17} /> Vision Analyst
            </span>
            <h2>{analysis.summary}</h2>
            <p className="vi-evidence-grounding">
              <IconShieldCheck size={15} /> Grounded in {analysis.evidence.length}{" "}
              Cosmos-inspected clip{analysis.evidence.length === 1 ? "" : "s"}
              {retainedCaptionCount > 0 && (
                <span>
                  {retainedCaptionCount} retained caption
                  {retainedCaptionCount === 1 ? "" : "s"}
                </span>
              )}
              {freshInspectionCount > 0 && (
                <span>
                  {freshInspectionCount} fresh visual inspection
                  {freshInspectionCount === 1 ? "" : "s"}
                </span>
              )}
              {analysis.evidence.length > 1 && (
                <span>Independent clips · identity not inferred</span>
              )}
            </p>
            {analysis.warning && (
              <p className="vi-evidence-degraded">
                <IconAlertTriangle size={15} /> {analysis.warning}
              </p>
            )}
            <div className="vi-evidence-claims">
              <div>
                <h3>
                  <IconCheck size={16} /> Observed
                </h3>
                <ClaimList
                  claims={analysis.observations}
                  evidenceById={evidenceById}
                  onOpenEvidence={onOpenEvidence}
                />
              </div>
              {analysis.interpretations.length > 0 && (
                <div>
                  <h3>AI interpretation</h3>
                  <ClaimList
                    claims={analysis.interpretations}
                    evidenceById={evidenceById}
                    onOpenEvidence={onOpenEvidence}
                  />
                </div>
              )}
            </div>
          </section>

          <aside className="vi-evidence-timeline">
            <span>
              <IconClock size={16} /> Evidence timeline
            </span>
            <ol>
              {analysis.timeline.map((entry) => {
                const clientId = evidenceById.get(entry.evidence_id);
                return (
                  <li key={entry.evidence_id}>
                    <button
                      type="button"
                      disabled={!clientId}
                      onClick={() => clientId && onOpenEvidence(clientId)}
                    >
                      <i />
                      <div>
                        <time>{formatClock(entry.start_time)}</time>
                        <strong>{entry.label}</strong>
                        <span>
                          {entry.source_name} · {entry.evidence_id}
                        </span>
                      </div>
                      <IconArrowRight size={15} />
                    </button>
                  </li>
                );
              })}
            </ol>
          </aside>

          <form className="vi-evidence-followup" onSubmit={submitQuestion}>
            <IconMessageCircle size={18} />
            <input
              aria-label="Ask about selected evidence"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a follow-up using only this evidence…"
              disabled={isAnalyzing}
            />
            <button type="submit" disabled={!question.trim() || isAnalyzing}>
              <IconArrowRight size={17} />
            </button>
          </form>

          {analysis.suggested_questions.length > 0 && (
            <div className="vi-evidence-suggestions">
              {analysis.suggested_questions.map((suggestion) => (
                <button
                  type="button"
                  key={suggestion}
                  disabled={isAnalyzing}
                  onClick={() => onAsk(suggestion)}
                >
                  {suggestion} <IconArrowRight size={13} />
                </button>
              ))}
            </div>
          )}

          <div className="vi-investigation-actions">
            {investigation ? (
              <div className="vi-investigation-saved">
                <IconShieldCheck size={18} />
                <div>
                  <strong>Investigation saved</strong>
                  <span>
                    {investigation.severity} severity · {investigation.id}
                  </span>
                </div>
                <a
                  href={investigation.report_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <IconFileReport size={15} /> View evidence report
                </a>
                <a
                  href={`${investigation.report_url}&download=true`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <IconDownload size={15} /> Export HTML
                </a>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setInvestigationTitle(analysis.summary.slice(0, 180));
                  setShowInvestigationForm(true);
                  setInvestigationError(null);
                }}
              >
                <IconShieldCheck size={16} /> Create incident and report
              </button>
            )}
          </div>

          {showInvestigationForm && (
            <form
              className="vi-investigation-form"
              onSubmit={createInvestigation}
            >
              <header>
                <div>
                  <IconShieldCheck size={18} />
                  <span>
                    <strong>Create investigation</strong>
                    <small>
                      Retains the briefing, ordered evidence, notes, and exact
                      playable citations locally on Thor.
                    </small>
                  </span>
                </div>
                <button
                  type="button"
                  aria-label="Cancel investigation"
                  onClick={() => setShowInvestigationForm(false)}
                >
                  <IconX size={16} />
                </button>
              </header>
              <label>
                Title
                <input
                  aria-label="Investigation title"
                  value={investigationTitle}
                  onChange={(event) =>
                    setInvestigationTitle(event.target.value)
                  }
                  maxLength={500}
                  required
                />
              </label>
              <div>
                <label>
                  Severity
                  <select
                    aria-label="Investigation severity"
                    value={investigationSeverity}
                    onChange={(event) =>
                      setInvestigationSeverity(
                        event.target.value as InvestigationSeverity
                      )
                    }
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </label>
                <label>
                  Disposition
                  <select
                    aria-label="Investigation disposition"
                    value={investigationDisposition}
                    onChange={(event) =>
                      setInvestigationDisposition(
                        event.target.value as InvestigationDisposition
                      )
                    }
                  >
                    <option value="open">Open</option>
                    <option value="under_review">Under review</option>
                    <option value="resolved">Resolved</option>
                    <option value="dismissed">Dismissed</option>
                  </select>
                </label>
              </div>
              <label>
                Operator notes
                <textarea
                  aria-label="Investigation notes"
                  value={investigationNotes}
                  onChange={(event) =>
                    setInvestigationNotes(event.target.value)
                  }
                  maxLength={5_000}
                  placeholder="Add context, actions taken, or handoff notes…"
                />
              </label>
              {investigationError && <p role="alert">{investigationError}</p>}
              <footer>
                <button
                  type="button"
                  onClick={() => setShowInvestigationForm(false)}
                >
                  Cancel
                </button>
                <button type="submit" disabled={investigationSaving}>
                  {investigationSaving ? (
                    <span className="vi-spinner" />
                  ) : (
                    <IconFileReport size={16} />
                  )}
                  {investigationSaving
                    ? "Saving locally…"
                    : "Save investigation"}
                </button>
              </footer>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
