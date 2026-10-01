# Spark booth browser rehearsal — September 30, 2026

Target: `http://10.88.9.91:7777/`, Codex in-app browser, real Spark backend.
Source: Spark Hospital Corridor, `3688c328-7e71-493c-a1c7-011ad2fb3893`.
Scene was static with visible medical equipment and no people.

## Actual checks

| Flow | Observed result |
| --- | --- |
| Live camera | Advancing 1280×720 video, readyState 4, no media error. Recording was already On. |
| Indexing | Count increased from 2160 to 2222+ and coverage advanced from17:28 to 17:33 EDT. After agent-only reload, explicit UI Pause / Resume reconciled the source to Active. |
| Initial people query | Failed semantic accuracy: hallucinated walking people. Correct sensor/time clip showed static equipment in sampled frames. |
| Neutral presence query | Passed: “No people are visible.”17:29:49–17:30:14 EDT. |
| Original query after backend prompt fix | Passed: “No people are visible in the video.”17:33:14–17:33:39 EDT. |
| Answer replay | Exact25.0013-second clip loaded1280×720, readyState 4. |
| Save answer | Report f388ab34-102b-45c1-a61f-31e5bae799af retained locally. |
| Search | “hospital beds and medical carts” returned 12 source-scoped candidates; first 4.4-second clip played. First request overlapped agent restart and failed; retry succeeded. |
| Positive visual rule | Visible-medical-cart condition yieldedTRUE. First result about 25 seconds after startup. Two initial event intervals17:34:25.729–17:34:48.263 and17:34:55.729–17:35:18.232 EDT. |
| Event review | Correct rule/source/time shown;22.5-second evidence played. Acknowledge changed review state and removed event from Needs attention. |
| Event report | Report a7a1d15d-61be-45fb-9824-9aa4224859bb retained clip; standalone report playback reached22.5-seconds, ended true, no media error. |
| Pause / Resume | Browser0/1 →1/1 →0/1. Backend confirmed actual original job quiescence17:40:41 EDT and resumed job creation17:40:53. Historical rule IDs retained. |
| Negative person rule | FALSE for 17:41:48.729–17:42:11.230 and17:42:18.729–17:42:41.230 EDT; zero persisted person incidents. Rule paused after test. |

## Fixes

- Replaced leading people/activity starter with a neutral presence question.
- Backend prompt checks requested entity presence and requires visible temporal evidence for motion; detector labels are not proof.
- Visual answer copy now asks the viewer to check the clip. Processing text explains retrieval, sampled frames and local vision reasoning.
- Camera indexing copy identifies Cosmos Embed and searchable segments; search explanation shows video/query embeddings and ranking.
- Added visual rulePause / Resume with real backend stop/start, exclusive visual lane, failure handling and historical backend ID association.
- Returning to Alert rules no longer automatically reopens the previous source wizard.

## Validation and limits

Strict app TypeScript check passed. Seven affected Jest suites / 91 tests passed,
including 7 monitoring API tests. Backend prompt source-function checks passed;
full backend pytest was not available in the runtime and is not claimed.
Browser console warning/error check empty at the desk checkpoint.
Memory guard remained 24 GiB; available memory checkpoints 30–32 GiB; boot ID unchanged
`6b100cd0-2daa-4ef5-8db5-2b4c0bee5201`. This is not a continuous telemetry soak.

No model budget changes or full-stack restart. Two agent-only reloads loaded the
prompt fixes. Both rehearsal rules were paused; capture/indexing preserved for further
user testing. Saved reports and acknowledged event remain development data.

Unqualified: positive avatar entrance/exit, hospital detector labels and counts,
accurate object similarity, world-space trajectories, multi-camera capacity,
sustained show-day runtime. Backend incident place metadata retains inherited warehouse
defaults; source identity shown by the app is the registered hospital camera.

Proof screenshots are local at
`/home/spark/.codex/visualizations/2026/09/30/vss-booth-rehearsal/`.
Presenter flow: [playbook](../demo-presenter-runbook.md).

## Broader summary regression

The first general summary claimed a distant person in red clothing, which the
static replay did not confirm. A second grounding correction requires clearly
identifiable human features and rejects ambiguous distant colored shapes as
people or clothing. The same summary query then described the static medical
equipment and no people at 17:48:13–17:48:38 EDT. Its exact 25.0013-second clip
played with no media error. This is a regression pass for this scene, not a
guarantee of broad model accuracy. Both agent reloads preserved model budgets;
explicit source Pause / Resume restored active ingestion afterward.

Desktop and 390×844 narrow desk inspected; no horizontal overflow. The broader
summary was first submitted from Live demo, then retested from Live cameras
through the same visual endpoint. Rehearsal rules remain paused.
