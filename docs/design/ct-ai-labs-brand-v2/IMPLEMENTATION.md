# CT AI Labs Vision Intelligence implementation map

This directory is the accepted visual concept set for the Thor VSS showcase. The mockups establish hierarchy, density, typography, color, and interaction tone. They are not a promise that invented airport data or unsupported model outputs exist.

## Product principles

- Lead with understanding, not a wall of raw video.
- Keep conclusions next to their source, timestamp, evidence, and provenance.
- Use warm white for the application canvas and near-black for video/hardware surfaces.
- Reserve teal for intelligence and interaction, green for healthy states, amber for watch states, and coral for attention.
- Prefer plain operational language over model and infrastructure jargon.
- Every visible action must use a real VSS route, source, or result. Unavailable capability is explained, never simulated.

## Information architecture

| Surface | Real implementation |
| --- | --- |
| Home | Environment brief assembled from live source state, indexed intelligence, incidents, and Thor health; prominent routes into evidence and live monitoring. |
| Live | Existing one-to-eight source grid and dedicated source workspace, including playback, Vision Analyst, evidence layers, pause/resume, analytics profile, and GraphRAG history. |
| Explore | Existing fusion search, filters, exact clips, visual-object search, evidence selection, Cosmos/Nemotron synthesis, follow-up, saved investigations, and report export. |
| Events | Existing consolidated incident activity and native operational insights. |
| Capabilities | Truthful guided entry points into semantic search, visual reasoning, live indexing, evidence synthesis, GraphRAG history, detection/tracking where configured, and alerting. |
| System | Real service readiness and Thor metrics alongside source and alert-rule administration. |

## Intentional deviations from the mockups

- The fixed airport scenario chooser is omitted. This deployment supports arbitrary warehouse, traffic, robotics, and simulator footage; the UI derives its context from connected sources.
- Persistent person identity, cross-camera re-identification, and the generated relationship graph are not claimed. Existing evidence relationships and source-scoped GraphRAG history remain available without implying biometric identity.
- Hardware values, workload rates, detections, and summaries are never hard-coded. Unavailable measurements use an honest unavailable state.
- Privacy/anonymization and action-recognition controls are not shown because they are not currently backed by this Thor runtime.
- Source and alert administration remain first-class under System because they are required to prepare a reliable tradeshow scenario.

## Fidelity ledger

The implementation is accepted against these comparison points:

1. A light, spacious shell with a persistent left rail and compact contextual top bar.
2. Home prioritizes an environment brief, global question, semantic source cards, and a quiet edge-status rail.
3. Live presents a stable multi-camera overview and a focused camera workspace without turning the landing page into a surveillance wall.
4. Explore makes natural language primary and presents retrieved video explicitly as supporting evidence.
5. Events keep verdict, location, time, clip, and review action adjacent.
6. Capabilities feel like a working lab bench and route into real demonstrations rather than static marketing cards.
7. System proves the on-device boundary with real service and hardware health while keeping administration close.
8. Mobile collapses the rail, preserves every primary destination, and keeps core actions reachable.

