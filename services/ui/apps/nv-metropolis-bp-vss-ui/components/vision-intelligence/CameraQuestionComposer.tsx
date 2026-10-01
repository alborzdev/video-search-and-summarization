// SPDX-License-Identifier: MIT

import {
  IconArrowRight,
  IconList,
  IconMessageCircle,
  IconPlayerPlayFilled,
  IconUser,
} from "@tabler/icons-react";
import React, { FormEvent, useState } from "react";
import { FootageDurationControl } from "./FootageDurationControl";

const prompts = [
  { text: "Describe the scene.", icon: IconMessageCircle },
  { text: "Are people wearing PPE?", icon: IconUser },
  { text: "Is there a forklift present?", icon: IconList },
];

export function CameraQuestionComposer({
  name,
  recorded = false,
  canAsk,
  isLoading,
  notice,
  questionBlockReason,
  onAsk,
  onStartCapture,
  lookbackSeconds,
  onLookbackSecondsChange,
  durationDisabled,
  children,
}: {
  name: string;
  recorded?: boolean;
  canAsk: boolean;
  isLoading: boolean;
  notice?: string;
  questionBlockReason?: string | null;
  onAsk: (query: string) => void;
  onStartCapture?: () => void;
  lookbackSeconds?: number | null;
  onLookbackSecondsChange?: (seconds: number | null) => void;
  durationDisabled?: boolean;
  children?: React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canAsk && !isLoading && query.trim()) onAsk(query.trim());
  };
  return (
    <section
      className="vi-camera-question"
      aria-label={recorded ? "Ask this recording" : "Ask this camera"}
    >
      <h2>{recorded ? "Ask this recording" : "Ask this camera"}</h2>
      <p className="vi-camera-question-intro">
        {recorded
          ? "Inspect this footage and replay the evidence."
          : "Inspect recent footage and replay the evidence."}
      </p>
      <div className="vi-camera-prompts">
        {prompts.map(({ text, icon: Icon }) => (
          <button
            key={text}
            type="button"
            aria-pressed={query === text}
            disabled={isLoading || Boolean(questionBlockReason)}
            onClick={() => setQuery(text)}
          >
            <Icon size={18} />
            <span>{text}</span>
            <IconArrowRight size={15} />
          </button>
        ))}
      </div>
      <form onSubmit={submit}>
        <label htmlFor="vi-camera-question">Your question</label>
        <textarea
          id="vi-camera-question"
          aria-label="Ask Vision Analyst"
          placeholder={
            notice?.includes("unavailable")
              ? "Visual reasoning is offline — check System readiness"
              : "Ask about this camera…"
          }
          maxLength={1000}
          disabled={isLoading}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {!recorded && onLookbackSecondsChange && <FootageDurationControl seconds={lookbackSeconds ?? null} onChange={onLookbackSecondsChange} disabled={isLoading || durationDisabled} />}
        <button
          type="submit"
          className="vi-camera-primary"
          aria-label="Send question"
          disabled={!canAsk || isLoading || !query.trim()}
        >
          {isLoading ? (
            <span className="vi-spinner" />
          ) : (
            <IconPlayerPlayFilled size={17} />
          )}
          {isLoading ? "Inspecting video…" : "Ask the video"}
        </button>
      </form>
      {notice && (
        <div className="vi-camera-notice" role="status">
          <p>{notice}</p>
          {onStartCapture && (
            <button
              type="button"
              className="vi-camera-button"
              onClick={onStartCapture}
            >
              Start live capture
            </button>
          )}
        </div>
      )}
      {children ?? (
        <div className="vi-camera-answer-empty">
          <IconMessageCircle size={22} />
          <div>
            <strong>Your answer appears here</strong>
            <p>Answers include the inspected time window.</p>
          </div>
        </div>
      )}
    </section>
  );
}
