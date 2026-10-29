# Recorded MV3DT evaluation clock

Recorded replay uses the worker's `recorded-pts` clock. Its `sourceTimeNs` starts from the replay process's epoch; it is not the original camera capture time. The evaluator must not compare that epoch directly to a previously captured actor trace or rename it `source-rtcp`.

The optional `--recorded-clock` input to `tools/smart-city/evaluate_mv3dt_probe.py` accepts a `city.encoded-pair-clock.v1` receipt produced by `verify_mv3dt_pair.py`. This is an offline scoring input. It does not change a camera, recorded packet, decoded buffer, tracker clock, observation timestamp or live gateway.

## Required evidence

1. The paired capture completes EOS finalization without capture errors. Its original media, per-access-unit sidecars and capture manifest remain intact.
2. The verifier checks the payload hash, order and size of every captured H264 access unit against the corresponding stored packet. It records exact stored packet PTS and the original reference metadata. Unknown reference epochs, reordered timestamps, interior discontinuities or missing interior reference metadata remain failures.
3. Both ordered source IDs match the calibration package, capture manifest, verifier and actual replay command. The replay launcher pins each file SHA256 and the verification receipt SHA256 before running the tracker.
4. At evaluation, the media, timing sidecars and capture manifest still match their verified hashes. The replay invocation's file hashes and URIs must refer to those exact capture files.
5. Every replay observation's `rawSourcePtsNs` must exactly match a stored packet PTS. The evaluator refuses to fit an offset if the decoder rebases timestamps or if the frame has no packet match.
6. The verifier and evaluator require a common recorded tracker-input clock. Across both complete mapped streams, `referenceUnixNs - filePtsNs` may vary by no more than the existing 50 ms skew gate. Mapping output to original reference time cannot repair a tracker that received two independently rebased files.

An initial prefix before actual reference metadata becomes available can remain unqualified, as with the live RTCP warm-up. The verifier counts that prefix explicitly. The evaluator excludes only those exact prefix packets and reports the number of excluded observations. A missing timestamp after the first valid reference is an error, not an excuse to drop a difficult sample.

## Scoring behavior

For each accepted recorded observation, the evaluator creates an internal `evaluationTimeNs` from the verified original packet reference. It keeps the worker's `sourceTimeNs` and `timestampBasis: recorded-pts` unchanged. Warm-up, actor-trace matching and cross-camera pairing use this explicit evaluation time. The result includes `clockEvidence` with the mapping hash, capture identity, mapped count, excluded prefix count and observed shared-clock offset spread.

The actual replay observations establish whether raw decoder PTS matches stored packet PTS. Therefore the pre-replay capture verifier keeps `replayAlignmentQualified: false`. Only the later evaluator can establish this particular relation from real replay metadata. That still does not establish physical exposure synchronization, precise render-to-actor-root alignment, label visibility, identity accuracy or native-position accuracy. The existing promotion gates remain separate.

For a candidate replay, use the same verification receipt in the launcher and evaluator:

```text
mv3dt_probe.py ... --recorded-clock-verification /absolute/capture/clock-verification-....json
evaluate_mv3dt_probe.py --run /absolute/probe-run --package /absolute/probe-run/package.json \
  --ground-truth /absolute/offline-actor-trace.ndjson \
  --recorded-clock /absolute/capture/clock-verification-....json --output /absolute/new-comparison.json
```

The source arguments must be the ordered, approved `file:///media/...` recordings. Use actual saved paths and preserve failed receipts. Recorded observations without the explicit verification input are rejected. Do not invent a mapping from host start time, change clock labels, independently zero the camera files, or replace capture timestamps with actor truth.

If the captured reference metadata or exact replay PTS correspondence is unavailable, the recorded comparison is unqualified. Use an explicitly live diagnostic with real source RTCP and a separate bounded held-out label trace instead. It is not a same-pixels A/B test.

## Validation status

The evaluator has 28 focused CPU controls, including an end-to-end labelled fixture whose replay epoch is deliberately unrelated to the original reference epoch. Tests cover exact mapping, unchanged emitted clocks, prefix accounting, changed media/sidecars/manifests, wrong source order/URI, interior missing clocks and cross-camera input-clock misalignment. The last run passed in 0.04 seconds. Both historical live-run metrics and original gate outcomes still reproduce exactly.

These controls establish the source contract only. No real recorded replay is claimed qualified by this document.
