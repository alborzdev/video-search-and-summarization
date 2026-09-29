// SPDX-License-Identifier: MIT

import type {
  EvidenceAnalysisClaim,
  EvidenceAnalysisResponse,
  EvidenceVisualInspection,
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
import React, { FormEvent, useRef, useState } from "react";

export interface SelectedEvidenceItem {
  clientId: string;
  endTime: string;
  imageUrl: string;
  matchType: string;
  sensorId: string;
  sourceName: string;
  startTime: string;
  startLabel?: string;
  durationLabel?: string;
  fromEarlierSearch?: boolean;
  title: string;
}

interface EvidenceAnalysisPanelProps {
  questionInputRef?: React.RefObject<HTMLInputElement>;
  analysis: EvidenceAnalysisResponse | null;
  error: string | null;
  isAnalyzing: boolean;
  items: SelectedEvidenceItem[];
  inspections?: EvidenceVisualInspection[];
  onAnalyze: () => void;
  onRetry: () => void;
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
  inspections = [],
  onAnalyze,
  onRetry,
  onAsk,
  onClear,
  onOpenEvidence,
  onRemove,
  questionInputRef,
}: EvidenceAnalysisPanelProps) {
  const [question, setQuestion] = useState("");
  const localQuestionInputRef = useRef<HTMLInputElement>(null);
  const inputRef = questionInputRef ?? localQuestionInputRef;
  const [showInvestigationForm, setShowInvestigationForm] = useState(false);
  const [investigationTitle, setInvestigationTitle] = useState("");
  const [investigationSeverity, setInvestigationSeverity] =
    useState<InvestigationSeverity>("low");
  const [investigationDisposition, setInvestigationDisposition] =
    useState<InvestigationDisposition>("under_review");
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
  const summaryIsObservation = analysis?.observations.length === 1 &&
    analysis.observations[0].text === analysis.summary;
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
  const questionForm = (
          <form className="vi-evidence-followup" onSubmit={submitQuestion}>
            <IconMessageCircle size={18} />
            <input
              ref={inputRef}
              aria-label="Ask about selected evidence"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={analysis ? "Ask a follow-up…" : items.length === 1 ? "Ask about this clip…" : "Ask about these clips…"}
              disabled={isAnalyzing}
              autoFocus={!analysis && !isAnalyzing}
            />
            <button type="submit" aria-label={analysis ? "Send evidence follow-up" : "Ask selected evidence"} disabled={!question.trim() || isAnalyzing}>
              <IconArrowRight size={17} />
            </button>
          </form>
  );
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
        ...(item.startLabel ? { start_label: item.startLabel } : {}),
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
            <IconSparkles size={16} /> Ask about selected clips
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
              ? "Describe again"
              : "Describe what happens"}
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
              <span title={item.sourceName}>{item.sourceName}</span>
              <span className="vi-evidence-tray-time">
                {item.startLabel ?? formatClock(item.startTime)}
                {item.durationLabel && ` · ${item.durationLabel} clip`}
              </span>
              <small>{item.fromEarlierSearch ? "Selected earlier · " : ""}{item.matchType}</small>
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

      {items.some((item) => item.fromEarlierSearch) && (
        <p className="vi-evidence-selection-context">Includes clips from earlier searches. Questions use the selection above.</p>
      )}

      {!analysis && questionForm}

      {!analysis && (
        <div className="vi-evidence-question-ideas" role="group" aria-label="Suggested evidence questions">
          <span>Try a question, or write your own.</span>
          {[
            { label: "What moves?", question: items.length === 1
              ? "What moves in this clip?"
              : "What moves in each clip?" },
            { label: "What is visible?", question: items.length === 1
              ? "What objects are visible in this clip?"
              : "What objects are visible in each clip?" },
          ].map((idea) => (
            <button key={idea.label} type="button" disabled={isAnalyzing}
              onClick={() => { setQuestion(idea.question); inputRef.current?.focus(); }}>
              {idea.label}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="vi-evidence-analysis-error" role="alert">
          <IconAlertTriangle size={17} />
          <span>{error}</span>
          <button type="button" onClick={onRetry} disabled={isAnalyzing}>
            Try again
          </button>
        </div>
      )}

      {isAnalyzing && !analysis && (
        <div className="vi-evidence-analysis-loading" aria-live="polite">
          <span className="vi-spinner" />
          <div>
            <strong>{inspections.length === items.length
              ? (items.length > 1 ? "Preparing the comparison" : "Preparing the answer")
              : inspections.length ? `${inspections.length} of ${items.length} clips inspected`
              : "Inspecting the actual selected footage"}</strong>
            <span>
              Your question is answered from the selected footage on this
              device. Each answer stays linked to its source clip.
            </span>
          </div>
        </div>
      )}

      {!analysis && inspections.length > 0 && (
        <section className="vi-evidence-partial" aria-label="Inspection progress" aria-live="polite">
          <strong>{error ? "Inspections completed before interruption" : `Results so far · ${items.length > 1 ? "comparison" : "answer"} pending`}</strong>
          {inspections.map((inspection) => (
            <article key={inspection.evidence_id}>
              <button type="button" onClick={() => onOpenEvidence(inspection.client_id)}>
                <IconPlayerPlay size={14} /> {inspection.evidence_id} · {inspection.source_name}
              </button>
              <p>{inspection.observation}</p>
            </article>
          ))}
        </section>
      )}

      {analysis && (
        <div className="vi-evidence-analysis" aria-live="polite">
          <section className="vi-evidence-answer">
            <span>
              <IconSparkles size={17} /> AI answer
            </span>
            <p className="vi-answer-question">You asked: {analysis.question || analysis.query}</p>
            <h2>{analysis.summary}</h2>
            {summaryIsObservation && (
              <div className="vi-summary-citation">
                <CitationButtons evidenceIds={analysis.observations[0].evidence_ids}
                  evidenceById={evidenceById} onOpenEvidence={onOpenEvidence} />
              </div>
            )}
            <p className="vi-evidence-grounding">
              <IconPlayerPlay size={15} /> Based on {analysis.evidence.length}{" "}
              AI-inspected clip{analysis.evidence.length === 1 ? "" : "s"}
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
            {typeof analysis.timings_ms?.total === "number" && Number.isFinite(analysis.timings_ms.total) && analysis.timings_ms.total >= 0 && (
              <details className="vi-analysis-timing">
                <summary>Local analysis: {(analysis.timings_ms.total / 1000).toFixed(1)} seconds</summary>
                <p>Time measured by the local analysis service. Upload, queue and browser delivery time are not included.</p>
                {([ ["inspection", "Footage inspection"], ["synthesis", "Answer preparation"] ] as const).map(([key, label]) => {
                  const duration = analysis.timings_ms?.[key];
                  return typeof duration === "number" && Number.isFinite(duration) && duration >= 0
                    ? <div key={key}>{label}: {(duration / 1000).toFixed(1)} seconds</div>
                    : null;
                })}
              </details>
            )}
            {analysis.warning && (
              <p className="vi-evidence-degraded">
                <IconAlertTriangle size={15} /> {analysis.warning}
              </p>
            )}
            <div className="vi-evidence-claims">
              {!summaryIsObservation && <div>
                <h3>
                  <IconSparkles size={16} /> AI observations
                </h3>
                <ClaimList
                  claims={analysis.observations}
                  evidenceById={evidenceById}
                  onOpenEvidence={onOpenEvidence}
                />
              </div>}
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
              <IconClock size={16} /> Check the video
            </span>
            <ol>
              {analysis.timeline.map((entry) => {
                const clientId = evidenceById.get(entry.evidence_id);
                const selectedItem = items.find((item) => item.clientId === clientId);
                return (
                  <li key={entry.evidence_id}>
                    <button
                      type="button"
                      disabled={!clientId}
                      onClick={() => clientId && onOpenEvidence(clientId)}
                    >
                      <i />
                      <div>
                        <time>{selectedItem?.startLabel ?? formatClock(entry.start_time)}</time>
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

          {questionForm}

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
                  <strong>Report saved</strong>
                  <span>
                    Answer, notes and video references saved locally.
                  </span>
                </div>
                <a
                  href={investigation.report_url}
                >
                  <IconFileReport size={15} /> Open report
                </a>
                <a
                  href={`${investigation.report_url}&download=true`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <IconDownload size={15} /> Download report
                </a>
              </div>
            ) : !showInvestigationForm ? (
              <button
                type="button"
                onClick={() => {
                  setInvestigationTitle((analysis.question || analysis.query).slice(0, 180));
                  setShowInvestigationForm(true);
                  setInvestigationError(null);
                }}
              >
                <IconShieldCheck size={16} /> Save report
              </button>
            ) : null}
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
                    <strong>Save an evidence report</strong>
                    <small>
                      Keep this answer, your notes and links to the selected video together.
                    </small>
                  </span>
                </div>
                <button
                  type="button"
                  aria-label="Cancel report"
                  onClick={() => setShowInvestigationForm(false)}
                >
                  <IconX size={16} />
                </button>
              </header>
              <label>
                Title
                <input
                  aria-label="Report title"
                  value={investigationTitle}
                  onChange={(event) =>
                    setInvestigationTitle(event.target.value)
                  }
                  maxLength={500}
                  required
                />
              </label>
              <details className="vi-report-review-details">
                <summary>Review details · {investigationSeverity} priority · {investigationDisposition.replace("_", " ")}</summary>
                <div>
                <label>
                  Review priority
                  <select
                    aria-label="Review priority"
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
                  Review status
                  <select
                    aria-label="Review status"
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
              </details>
              <label>
                Notes (optional)
                <textarea
                  aria-label="Report notes"
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
                    : "Save report"}
                </button>
              </footer>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
