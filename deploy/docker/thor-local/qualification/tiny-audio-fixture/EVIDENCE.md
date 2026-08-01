# Evidence and non-evidence boundary

## What is statically enforced

`fixture.py` and `receipt.schema.json` establish these controls:

- no-argument/default execution is a write-free, subprocess-free plan;
- generation requires an exact acknowledgement and an absolute `.mp4` output
  outside the resolved repository root;
- media and adjacent receipt destinations must both be absent;
- filenames are restricted to safe ASCII characters;
- partial output is isolated in a newly owned mode-0700 work directory and
  publication uses non-overwriting hard links;
- only local `ffmpeg` and `ffprobe` are subprocess-admissible;
- canonical tool paths are restricted to root-owned, non-group/world-writable
  sanitized roots and each tool path and SHA-256 is recorded;
- subprocesses use argument arrays, `shell=False`, a fixed minimal environment,
  no stdin, fixed timeouts, `file,pipe` protocol whitelists, and incremental
  131,072-byte stdout / 16,384-byte stderr capture limits;
- the fixed recipe uses only `lavfi` `color`, `drawtext`, and `flite` inputs;
- generated media must be at most 2,000,000 bytes and have exactly one bounded
  H.264 video stream and one bounded AAC-LC mono audio stream;
- the receipt has a 65,536-byte ceiling, rejects duplicate JSON keys and all
  unknown schema properties, and locks the three exact gap identifiers;
- the receipt schema is bounded, opened with `O_NOFOLLOW`, and raw-SHA pinned;
- verification pins regular inputs with `O_NOFOLLOW` descriptors, hashes and
  probes the media through that descriptor, and rejects identity, metadata, or
  content instability without performing a write operation;
- an EEXIST publication race preserves every competing inode; no pathname
  rollback can delete a replacement file.

The phrase is locked as both literal UTF-8 text and SHA-256:

```text
Attention operator. The blue crate is ready.
c20db4dfe2b82f3a2ebeb1cfc053e7b63baa3cf079140466827342930d641ec8
```

The normalized generator recipe is locked as:

```text
ef0765520b8efae3cd2258762cd9a0c20d9cfdc2360611aa8776139571589a3c
```

The final raw receipt schema is locked as:

```text
11b379f215d54ae6c7fdc42e5680059a69d2b5a41b162d257b313e9ad3f11793
```

## Executed checks

The default focused suite was executed on Thor with bytecode writes disabled:

```text
40 passed, 1 skipped in 0.58s
```

The single opt-in local integration was then executed explicitly. It generated
the fixture under pytest's fresh external temporary directory, schema-validated
the receipt, and completed read-only verification against a fresh `ffprobe`
observation:

```text
1 passed in 0.63s
```

The temporary integration artifact was not retained and no binary artifact or
generated receipt is part of this package.

## What this does not prove

These checks prove fixed-recipe fixture generation and individual artifact
integrity only. They do not prove byte-identical output across tool builds or
semantic recognition of the spoken phrase. They do not execute
the Base profile, RT-VLM chunking, LVS summarization, or alerts; do not load an
audio-capable VLM or ASR service; and do not establish a transcript or semantic
match from a VSS response. They therefore provide no runtime evidence and do
not change any capability state.

The three target oracles still require the generated media to be admitted by a
bounded local audio workflow and correlated with transcript or semantic output
and a workflow response transcript. The per-chunk transcript gap additionally
requires a transcript-producing ASR path. No Warehouse sample data is required
or used by this fixture lane.
