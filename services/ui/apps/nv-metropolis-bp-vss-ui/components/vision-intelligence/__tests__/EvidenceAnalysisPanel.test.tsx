import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { EvidenceAnalysisPanel } from "../EvidenceAnalysisPanel";

it("asks a specific evidence question without requiring an initial general analysis", () => {
  const onAsk = jest.fn();
  const onAnalyze = jest.fn();
  render(<EvidenceAnalysisPanel analysis={null} error={null} isAnalyzing={false}
    items={[{ clientId: "clip", sensorId: "source", sourceName: "Recording", title: "Movement", startTime: "2025-01-01T00:00:00Z", endTime: "2025-01-01T00:00:05Z", imageUrl: "", matchType: "Semantic Match" }]}
    onAsk={onAsk} onAnalyze={onAnalyze} onRetry={jest.fn()} onClear={jest.fn()} onOpenEvidence={jest.fn()} onRemove={jest.fn()} />);
  expect(screen.getByRole("button", { name: "Ask selected evidence" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Ask about selected evidence"), { target: { value: "  What is visible at the end?  " } });
  fireEvent.click(screen.getByRole("button", { name: "Ask selected evidence" }));
  expect(onAsk).toHaveBeenCalledWith("What is visible at the end?");
  expect(onAnalyze).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Ask about selected evidence")).toHaveValue("");
});

it("shows completed inspections as partial evidence without enabling report saving", () => {
  const onOpenEvidence = jest.fn();
  render(<EvidenceAnalysisPanel analysis={null} error={null} isAnalyzing={true}
    items={[{ clientId: "clip", sensorId: "source", sourceName: "Recording", title: "Movement", startTime: "2025-01-01T00:00:00Z", endTime: "2025-01-01T00:00:05Z", imageUrl: "", matchType: "Semantic Match" }]}
    inspections={[{ client_id: "clip", evidence_id: "E1", source_name: "Recording", start_time: "2025-01-01T00:00:00Z", end_time: "2025-01-01T00:00:05Z", observation: "A worker holds a box.", inspection_source: "fresh_cosmos_inspection", match_type: "Semantic Match" }]}
    onAsk={jest.fn()} onAnalyze={jest.fn()} onRetry={jest.fn()} onClear={jest.fn()} onOpenEvidence={onOpenEvidence} onRemove={jest.fn()} />);
  expect(screen.getByRole("region", { name: "Inspection progress" })).toHaveTextContent("Results so far");
  expect(screen.getByText("A worker holds a box.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save report" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "E1 · Recording" }));
  expect(onOpenEvidence).toHaveBeenCalledWith("clip");
});

it.each([undefined, {total: NaN}, {total: -1}, {total: 17570, inspection: 17560, synthesis: 10}])("shows only valid measured service timing: %p", (timings_ms) => {
  render(<EvidenceAnalysisPanel analysis={{timings_ms, evidence: [], interpretations: [], observations: [], query: "boxes", question: "What happened?", status: "complete", suggested_questions: [], summary: "Visible activity", timeline: []}} error={null} isAnalyzing={false} items={[]}
    onAsk={jest.fn()} onAnalyze={jest.fn()} onRetry={jest.fn()} onClear={jest.fn()} onOpenEvidence={jest.fn()} onRemove={jest.fn()} />);
  if (timings_ms?.total === 17570) {
    expect(screen.getByText("Local analysis: 17.6 seconds")).toBeInTheDocument();
    expect(screen.getByText(/Upload, queue and browser delivery time are not included/)).toBeInTheDocument();
  } else expect(screen.queryByText(/Local analysis:/)).not.toBeInTheDocument();
});
