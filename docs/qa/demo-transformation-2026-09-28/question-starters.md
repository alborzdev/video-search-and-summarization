# Evidence question starters

## Finding and change

Rehearsed Home → Find a person carrying a box → Play clip → Ask about this
clip in the Codex integrated browser. Search returned one real matching clip;
the viewer opened and its ask action focused the selected-evidence input.
The next step offered an empty input and generic description action, leaving a
first-time visitor to invent a useful question.

Added two editable starters in `EvidenceAnalysisPanel.tsx`: “What moves?” and
“How does it end?” They fill “What moves in this clip?” / “How does this clip
end?”, using “each clip” for multiple selections. They do not submit a request.
The existing submit action sends the visitor's editable question. Suggestions
are disabled during analysis and omitted once an answer exists. Existing
description and freeform controls remain available.

The first draft used long explanatory prompts. Mobile inspection showed these
were difficult to review in the input; replaced them with short ordinary
questions. CSS wraps the buttons and gives the helper text its own mobile line.

## Verification

- Environment: `http://10.88.9.12:7777/`, Codex integrated browser, default
  desktop viewport and 390 × 844; viewport override reset afterward.
- Page identity/content: Vision Intelligence, Home then Search video; passed.
- No blank page or framework overlay in inspected states.
- Browser warning/error log: empty during this flow.
- Both starter interactions populated and focused the editable input; submit
  enabled and no analysis/loading state was triggered by choosing a starter.
- Actual final short “How does this clip end?” checked at both viewport sizes.
- Typecheck passed; existing InvestigateWorkspace suite passed 20/20. Final
  follow-up edits only shorten string literals and adjust responsive CSS.
- Screenshots: `question-starters-desktop.png`, `question-starters-mobile.png`.

No new inference submitted or report saved in this check. The pre-inference
runtime check passed all 31 core roles with 48.78 GiB available; deferred extra
vision workload at this narrow margin above the unchanged 48 GiB guard.
These checks prove the UI interaction, not answer accuracy for these suggested
questions or multi-clip behavior. Fresh-answer rehearsal remains required.
