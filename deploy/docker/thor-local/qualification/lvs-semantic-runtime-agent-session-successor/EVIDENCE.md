# Evidence boundary

This directory contains source-locked code, schemas, an inert compiler plan,
and mock-only tests. It contains no deployed execution receipt and creates no
runtime evidence by default.

Static evidence proves that the current production sources retain:

- the selected schema-v2 500-row LVS oracle in `open_unexecuted` state with
  null executors/cleanup collectors and its frozen 14/14 envelope;
- the four LVS workflow tools plus the `report_agent` binding to
  `video_report_gen`;
- NAT WebSocket user-message conversation identity and HITL reply
  `thread_id`/`parent_id` semantics;
- per-conversation LVS HITL state, latest-state replacement, and shared
  multi-video parameters;
- response-generated per-sensor Markdown/PDF report names and exact object-key
  GET/DELETE routes.

Mock evidence covers acknowledgement-before-caller-manifest validation and CLI
manifest reads, authorization-before-I/O, two distinct sessions and
conversations, ordered HITL state transitions, one- and two-source report
artifacts, latest-state persistence, cross-session isolation, report-agent
response correlation, rejection of interaction-only old report URLs, Markdown
UTF-8 and PDF signature validation, exact reverse cleanup, post-delete 404,
collision failure cleanup, fixture ambiguity, and proxy rejection. Mocks are
not evidence that a Thor deployment passed.

Outstanding deployed evidence is enumerated in `contract.json`; no canonical
state, promotion, or executor-ready claim is made.
