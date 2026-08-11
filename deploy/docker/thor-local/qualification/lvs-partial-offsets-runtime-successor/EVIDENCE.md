# Evidence

- Capability: `manifest-entry.video-summarization-file.06-partial-video-offsets`.
- Positive selector: exact offset interval 3–6 seconds over one digest-pinned nine-second owned MP4.
- Semantic oracle: only the planted green in-range phase may appear; blue-before and red-after markers are forbidden.
- Timeline oracle: every returned event must retain original source time within 3–6 seconds, and the completion envelope must echo the selector exactly.
- Adjacent negative: start offset 6 with end offset 3 must return JSON HTTP 422.
- Runtime boundary: current healthy `vss-lvs`, exact advertised local model, numeric loopback only, no service lifecycle action.
- Cleanup: only the executor-owned upload is deleted and the complete pre-test catalog is restored.
- Warehouse sample bundle: excluded.
