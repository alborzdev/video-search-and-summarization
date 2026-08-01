# Audio advertised-entry oracles

This isolated package is an inert planner and read-only validator for the three
audio entries selected as static source candidates in
`advertised-entry-executors-wave7`:

- audio-aware Base workflow;
- audio transcript per RT-VLM chunk;
- audio-aware summarization and alerts.

It does not start VSS, load a model, call an endpoint, generate media, download
assets, or modify a ledger. No runtime receipt is bundled, so this package
makes no current runtime claim.

## The required two-lane distinction

The native-audio lane is for Base, LVS summary, and alert semantics. It requires
the pinned local Nemotron Omni identity, `audio_support=true`,
`VLM_MODEL_SUPPORTS_AUDIO=true`, per-request audio enablement, the 80 GiB plus
fixed-reserve memory gate, loopback endpoint evidence, and enabled-versus-muted
known-phrase correlations.

That lane cannot prove `audio_transcript`. RT-VLM deliberately skips its ASR
process when the VLM handles audio natively.

The transcript lane is separate. It requires
`VLM_MODEL_SUPPORTS_AUDIO=false`, `enable_audio=true`, a healthy local Riva
ASR process, a nonempty timed chunk transcript containing the full normalized
known phrase, and RT-VLM response capture. Evidence saying that native Omni
handled audio while ASR was skipped is rejected even if it supplies a claimed
transcript string. The native and transcript runs require distinct run and
authorization IDs; one acknowledgement cannot authorize both lanes.

## Read-only use

Render the current plan:

```bash
python deploy/docker/thor-local/qualification/audio-entry-oracles/oracle.py --json
```

Validate a future candidate receipt stored outside the repository:

```bash
python deploy/docker/thor-local/qualification/audio-entry-oracles/oracle.py \
  --validate-evidence /absolute/external/audio-candidate-evidence.json --json
```

The validator reads the evidence receipt and every referenced artifact. It
requires regular non-symlink files outside the checkout, bounded sizes, exact
SHA-256 and size matches, the existing tiny-audio fixture receipt and media
binding, strictly parsed model responses and snapshot entries, phrase and
control correlations, resource gates, ASR intervals contained in their exact
media chunks, ordered chunk timing, and exact executor-owned cleanup.

A successful validation returns
`validated_for_review_not_admitted`. It never marks a capability passed and
still requires human review plus a separate, explicit live-ledger integration.

Run the adversarial suite:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/audio-entry-oracles/tests
```

The Warehouse sample bundle is excluded throughout.
