# Audio oracle evidence boundary

## Static inputs locked by the planner

The contract raw-locks 23 repository files:

- the Wave 7 advertised-entry inventory and schema;
- the advertised-gap plan, manifest, acceptance inventory, official capability
  ledger, and capability-oracle ledger;
- the tiny known-speech fixture generator, strict receipt schema, and boundary
  documentation;
- RT-VLM pipeline and stream-handler sources that distinguish native audio from
  the actual ASR route and propagate `audio_transcript`;
- agent video-understanding/report sources and Base/Thor profile configuration;
- the Thor audio lane README, mutually exclusive Omni overlay and command
  renderer; and
- the pinned snapshot verifier and unified-memory budget implementation.

The known input is locked to:

```text
Attention operator. The blue crate is ready.
c20db4dfe2b82f3a2ebeb1cfc053e7b63baa3cf079140466827342930d641ec8
```

All three advertised entries remain absent from the live capability and oracle
ledgers. Their required plan oracles remain `open_unexecuted` with empty
runtime evidence.

## Future evidence requirements

The evidence schema and semantic validator require:

- an externally stored tiny-fixture receipt and matching media bytes;
- full normalized phrase correlation in the audio-enabled Base response, LVS
  summary, and alert, with audio-disabled controls that do not leak the
  audio-only phrase;
- a distinct, separately authorized non-native-audio run with a created,
  healthy local ASR process and exactly one timed chunk containing the full
  phrase in a nonempty `audio_transcript`, with the ASR interval contained in
  that exact fixture-media chunk;
- configured/observed model identity equality, strictly parsed `/v1/models`
  identity/audio-support evidence, a pinned 40-character Omni revision, strict
  snapshot file paths/digests/sizes with exact count and size sum, and
  loopback-only RT-VLM/Riva endpoints;
- the 80 GiB Omni admission floor, the fixed 20% reserve combined with the
  pinned 0.45 utilization, at least that 20% reserve still available during
  and after the run, one-process/batch/sequence limits, bounded ASR resources,
  and zero OOM observations; and
- distinct run timing followed by exact deletion of executor-owned resources,
  stopped native and transcript services, no remaining stream IDs, preservation
  of the operator-owned fixture, and a raw cleanup capture.

## What a validator pass does not prove

The validator authenticates the declared receipt structure, raw artifacts, and
cross-correlations. It does not execute VSS or independently witness the
runtime that produced those artifacts. A forged but internally consistent
external evidence bundle is therefore still possible and is why a pass is only
a candidate for human review, never automatic acceptance.

The fixture receipt proves bounded media identity, not semantic recognition.
Native Omni semantic output can support the Base/summary/alert candidates but
cannot support the per-chunk transcript candidate because the locked RT-VLM
source skips ASR for native-audio models. No future evidence has been bundled,
no current runtime claim is made, and no live ledger is changed.
