# Repeated recorded presenter rehearsal

September 28, 2026; Codex integrated browser, desktop at http://10.88.9.12:7777/.

## Outcome

Home → conveyor search → evidence viewer → fresh question → saved report →
copy briefing → Home completed in 96.028 seconds of agent wall time, including
inspection and tool pauses. This is not a scripted human-presentation timing.

- Search result observed by 3.410 seconds; one matching ten-second clip.
- Question: “What moves in this clip?” Answer: “A box moves along a conveyor belt.”
  UI reports 7.6 seconds of local analysis. Browser observation was still pending
  at 7.748 seconds and complete at 23.176 seconds after intervening inspection;
  do not report that observation gap as measured inference latency.
- Saved report `700d0588-90f7-4afd-8a19-0cbd15309388`, title **Presenter rehearsal —
  conveyor movement**, with explicit recorded-simulation review notes.
- Actual clipboard text contains the saved answer, notes, status and E1 link.
- Reopened the report again and visually verified retained video at 0:10 / 0:10.
  [Playback screenshot](rehearsal-repeat-playback.png), [report](rehearsal-repeat-report.png).
- Returning Home retains the selected recording. Its first loading snapshot
  briefly exposes “Unable to play media”; subsequent state has advancing playback
  and Searchable status. Investigate this loading flash in the next UI pass.
- The report's disabled “Playing exact clip” label remains after video ends;
  native replay controls remain available. Track this stale label for correction.

## Change found during the walkthrough

The selected-evidence panel still suggested “How does it end?”, despite known
end-state reasoning failures. Replaced that shortcut with “What is visible?”
which fills “What objects are visible in this clip?” (or each clip for multiple
selections). It does not submit automatically or change the model.

Six existing panel tests and app TypeScript pass. Codex browser verified the new
shortcut fills the expected question. No inference request was made for that
shortcut during this run; its accuracy is not established by this UI check.
[Updated suggestion](rehearsal-question-suggestion.png). No browser warning/error
entries captured.

## Runtime and scope

Guard active, 48 GiB floor unchanged. Preflight: all 31 core checks pass at
49.36 GiB available. Post-rehearsal: all 31 pass at 49.30 GiB. Both detectors stay
stopped and no continuous ingestion was started. Memory telemetry accompanies
this receipt. This recorded run does not qualify sustained workload or resolve
live misses, simulator reset, or downloaded HTML/PDF delivery.

Telemetry: 240 one-second samples, 48.466–49.577 GiB available; final disk free 15.88 GiB. Boot IDs: ac75a3b5-980a-41c5-8301-200423326f72. Minimum headroom above the guard was only 0.466 GiB. [Raw samples](rehearsal-repeat-memory.jsonl).
