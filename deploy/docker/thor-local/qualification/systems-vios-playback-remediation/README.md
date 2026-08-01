# VIOS playback-remediation qualification plan

This package materializes a bounded, offline-only qualification design for the
planning requirement `systems-vios-playback-remediation`. It does **not**
qualify VIOS runtime behavior and cannot promote the canonical capability.

The compiler binds all of the following exactly:

- capability `behavior.vios.upload-playback-remediation`;
- oracle `oracle.behavior.vios.upload-playback-remediation` at canonical index
  233 and its canonical digest;
- the verified 8-request / 9-action execution-bound integration;
- planning-requirement ownership in `acceptance_inventory.json`; and
- the existing `local20-vios-remediation-v1` fixture, its manifest entry,
  schema, and raw digest.

The planned future workflow captures prestate, classifies the VPN limitation as
a transport concern, models the incompatible B-frame failure, records a local
transcode intent (`bframes=0`, `keyint=30`), records exact resource ownership,
models remediated replay/readback, rejects adjacent wrong settings, cleans only
the owned derived resource, and verifies restoration. The sequence is the exact
canonical expansion:

1. `capture-pre-state`
2. `measure-vpn-upload-transport`
3. `observe-incompatible-playback`
4. `reencode-local-fixture` (zero request cost)
5. `upload-remediated-fixture`
6. `verify-synchronized-playback`
7. `reject-wrong-encode-settings`
8. `restore-owned-state`
9. `verify-postconditions`

## Safety boundary

There is no `execute` command and no network, subprocess, Docker, service
lifecycle, download, or Warehouse-data adapter. The default and only CLI command
compiles an inert JSON plan:

```bash
python deploy/docker/thor-local/qualification/systems-vios-playback-remediation/collector.py
```

`simulate_fake_transport()` is a test seam, not a runtime path. It accepts only
an exact, bounded, plain built-in transcript with no callbacks, validates every
scripted observation against a closed schema, and records zero runtime requests
and actions. Arbitrary transport objects are rejected without invoking caller
code. It intentionally cannot generate or transcode the local20 media, and its
output is never runtime evidence.

Run the fake-only test suite with:

```bash
pytest -q deploy/docker/thor-local/qualification/systems-vios-playback-remediation/test_collector.py
```

## Promotion blockers

The plan and fake simulation do not observe a VIOS response, actual media bytes,
an upload, a transcode, replay, a delayed playback-ready transition, a
synchronized playback window, or a late cleanup race. Those observations would
need a separately reviewed, explicitly authorized runtime collector before the
canonical `open_unexecuted` state could change.
