# Isaac intersection qualification — 2026-10-23

The final [summary](integrated-summary.json), [pipeline receipt](integrated-600s.json) and [simulator receipt](isaac-600s.json) passed. They qualify this exact two-camera Spark configuration, not MV3DT fusion or production detection accuracy.

- [Operator guide](../../smart-city-isaac-integration.md).
- [Actual live presentation](live-presentation-desktop.jpg), [real Ask and clip](live-ask-desktop.jpg).
- [Southwest Ask facts](live-ask-browser.json), [northeast Ask facts](live-ask-northeast.json), [northeast playback](northeast-evidence-playback.json).
- [Deployment identities](deployment-identities.json), [UI package](ui-package.json), [CPU checks](cpu-checks.json), [native policy](native-policy-runtime.json).
- [MV3DT first candidate](mv3dt-road-plane-comparison.json), [person-plane candidate](mv3dt-person-plane-comparison.json), [ground-association candidate](ground-association-comparison.json). All failed their quality gates and remain disabled.
- [Report API export](report-export-api.json); the in-app browser download event remains unverified.

Raw observations, held-out simulator labels, monitor samples and diagnostic logs are preserved in the private runtime directories referenced by the operator guide. Labels never feed operational RTSP, detections, tracks or the map. The initial 204.13-second interrupted diagnostic run is not a pass. Original media and unrelated work remain preserved.
