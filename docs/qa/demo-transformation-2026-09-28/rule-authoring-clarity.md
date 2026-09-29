# Monitoring rule authoring clarity

Continued September 28 demo audit; verified through the Codex integrated browser.

## Findings and changes

- New rules selected a disconnected Isaac camera despite a connected conveyor replay. Prefer an explicitly requested source, then a connected live source, then recorded footage, before other catalog entries.
- Generic prefilled conditions could be activated without describing a useful event. Visual rules now begin blank and require a concrete condition; Continue also waits for source profile readiness.
- Keyword inference could override an explicitly selected visual rule (for example, a question containing “forklift near”). Preserve the selected rule type and typed intent when choosing a template.
- Review now explains sampled video windows and repeated matches. Removed the visual-rule cooldown control and card claim because the live-alert API does not apply it. Detection rules retain their supported cooldown. The stored field remains for schema compatibility.

Changed `AlertRulesWorkspace.tsx`, `monitoringRules.ts`, and focused component tests.

## Verification

- 10 focused Jest tests passed; affected app TypeScript check passed.
- Codex browser: connected conveyor replay selected, empty draft cannot continue, concrete condition survives Continue and Back, review displays the exact condition and sampled-window explanation, no visual-rule cooldown shown.
- Desktop and 390 × 844 mobile review inspected; mobile Back and close worked. Viewport reset and draft discarded. No rule activated or inference workload started.
- Browser warning/error log query returned no entries.
- Screenshots: [desktop review](rule-authoring-review-desktop.png), [mobile review](rule-authoring-review-mobile.png), [condition entry](rule-authoring-condition-desktop.png).

This improves authoring clarity, not classification accuracy. The unresolved live miss from the [any-frame trial](alert-any-frame-live-trial.md) remains. Runtime cadence and memory safeguards are unchanged.
