# Smart City backend, controller, and native polish review

Date: 2026-10-22. Scope: the backend correctness/performance fixes, controller lifecycle and import caching, native analytics reload, bounded observation output, and its qualification reader. This is a code-review and CPU-test record. It does not claim completion of the coordinator's post-deployment combined GPU/UI/Ask qualification.

## Concrete fixes

| Area | Confirmed problem | Resulting behavior |
| --- | --- | --- |
| Event queries | Source/rule/state filters ran after fetching the latest 1,000 event records. An older matching record could disappear behind unrelated recent events. | `/api/v1/city/events` applies site/source/rule/state predicates in parameterized SQL before `LIMIT`. Response shape is unchanged. A site/update index supports the query. |
| Historical frame retention | Maintenance every 32 global writes pruned only the source that happened to arrive at that boundary. Alternating sources could leave one camera unpruned indefinitely. | Each maintenance pass prunes every over-limit source. The source/id index also avoids the latest-session temporary sort. The existing serialized-byte quota remains active. |
| Incident identity | Distinct incidents or crossings with increasing sequences but identical source timestamps shared an event ID and overwrote one another. | Incident IDs include the candidate's start sequence as well as its start timestamp. Continuous candidates retain one identity, and duplicate observation retries remain rejected. Existing stored event IDs are preserved. |
| Health cost and stale state | Health called the full display snapshot, copying tracks, trails, and events. A stale rule could retain a nonzero active-event count after its event became unknown. | Health uses a small source/status projection while retaining the same freshness/expiry maintenance. Stale rules report unknown with zero active-event count. Display snapshots remain available through their original route. |
| Failed removal | The controller removed ownership from memory before gateway configuration and persistence succeeded. A gateway failure left memory empty, disk unchanged, and a retry incorrectly returned “Already absent.” | Failed configuration/persistence restores retryable source ownership and attempts canonical rollback. The worker remains stopped after a failed transaction. A later successful removal remains idempotent. Archived custom rules survive a partial gateway update and rollback. |
| Readiness cost | Fresh imports of `manage.py` and `model_profile.py` discarded the stat-keyed artifact hash cache on every readiness request. | Imported modules are memoized. Every request still validates the selected model/receipts, actual-device requirement, saved headroom, and gateway. Artifact changes invalidate digest entries through file identity, size, mtime, and ctime. No readiness result is cached. |
| Native reload generation | Reading configuration A and then taking the watched path's mtime could mark replacement B consumed without ever applying B. | A bounded descriptor read associates immutable bytes with the descriptor's identity. Atomic replacement remains visible to the watcher, including replacement that preserves mtime. Concurrent in-place mutation is rejected and retried. |
| Native reload resources | Each edit retained another temporary INI until worker exit and could add another pending blocking probe during a source stall. | One permanent blocking buffer probe applies the latest pending generation. At most the current and newest pending snapshot files remain owned. Superseded pending files are removed. Revision/counter-epoch acknowledgement becomes active only after a frame has passed the updated analytics element. |
| Continuous raw observations | Managed continuous runs wrote and flushed NDJSON forever with no rotation. Read-only inspection found 29 existing observation files totaling 3,927.83 MiB, the largest 3,159.35 MiB. | Managed **live** launches use a new stable rolling family. Existing timestamped qualification artifacts and finite-run output behavior are untouched. |
| Rotation reader | A final row appended after reader EOF but before manifest acquisition could be lost when the reader closed the now-sealed inode. | After the manifest proves a generation sealed, the reader rechecks that open descriptor's size and drains any newly arrived bytes before switching. A deterministic race regression reproduces the original loss and verifies the fix. |

The changes retain the source/session/calibration gates, nullable uncalibrated map positions, bounded preview storage, and exact source/session/sequence/time/model/image correlation used for processed JPEG preview. They introduce no new global identity or calibrated fusion claim.

## Native output and reader contract

Managed live launch arguments are:

```text
--output /state/live-observations.ndjson
--output-max-bytes 268435456
--output-retained-files 2
```

`retained-files=2` means **two previous files plus current**, each at most 256 MiB: at most **768 MiB of visible NDJSON payload** in this new family across future sessions. Rotation renames current to `.1`, `.1` to `.2`, and retires only the oldest file in this family. It happens before a complete newline-terminated record. Writer reopen appends rather than truncates. Oversized records, partial final records, unknown generations, inconsistent manifests, or interrupted rotation state fail explicitly without repair or truncation. A stable `.lock` uses an exclusive lifetime `flock` to reject a second writer. Small manifest/lock metadata and temporarily open unlinked reader descriptors are separate from the visible-payload cap.

`live-observations.ndjson.manifest.json` has schema `city.observations.rotation.v1`, a monotonic decimal-string generation, numeric `maxBytes` and `retainedFiles`, and contiguous current-to-oldest entries containing `name`, decimal-string `generation`, `device`, and `inode`. An atomic manifest commit precedes the first record in the new generation. The writer seals an old generation before publishing it as retired.

The reader validates the exact retained-file count, contiguous generations, fixed family basenames, and unique device/inode identities. It drains its old descriptor before opening the next listed generation. A transient rename/manifest mismatch may wait, but a mismatch persisting for more than two seconds on a subsequent check fails. Missed retention, truncation, partial sealed records, unknown replacement, or generation rollback fail; sequence/session/PTS/source-clock counters remain continuous across rotations. Receipt output includes `observationRotations`. Legacy files without a manifest retain their original replacement/truncation rejection.

Native rotation defaults remain **off** for existing finite qualification calls. The native helper permits zero previous files; the rotation-aware monitor supports one to eight previous files. The managed profile uses two, which is the reviewed shared configuration.

## Executed checks

The final combined CPU invocation was:

```bash
PYTHONPATH=services/analytics/behavior-analytics \
  /tmp/vss-city-backend-test-env/bin/python -m pytest -q \
  services/analytics/behavior-analytics/apps/city/tests \
  tools/smart-city/test_controller.py \
  tools/smart-city/test_manage.py \
  tools/smart-city/tests/test_model_profile.py \
  tools/smart-city/tests/test_soak.py \
  -W error::ResourceWarning
```

Result: **163 passed, four subtests passed, 2.05 seconds**. The sole warning was the existing Starlette/httpx deprecation warning. The component totals were 82 gateway/backend tests, 54 controller/manage/model-profile tests, and 27 monitor tests. Tests used private fixtures and mocked OS/service boundaries; they did not start Docker, detector services, RTSP readers, or GPU work.

Additional completed checks:

- Full Ruff on `controller.py`, `test_controller.py`, `store.py`, and `tests/test_store.py`: passed. Ruff correctness rules `E9,F63,F7,F82` on the changed engine/main/manage and corresponding tests: passed. Broader pre-existing style issues were not rewritten. Python compilation of the changed Python files passed.
- Independent backend review and private CPU checks confirmed health response equivalence for setup, awaiting observations, partial sources, and stale sources; event identity recurrence/retry behavior; and SQL filter forwarding with unchanged response keys.
- Delegated native helper tests `test_analytics_config.cpp` and `test_rolling_output.cpp`: passed both normal `-O2 -std=c++17 -Wall -Wextra -Werror` builds and ASan/UBSan builds. These compiled CPU helpers, not a detector/GPU pipeline. Controls include replacement during descriptor read, preserved-mtime replacement, in-place mutation, 1,000 stalled-source edits with exactly current/pending snapshots, deferred activation, complete-record rotation, append reopen, exclusive writer rejection, partial-record/corrupt-manifest/crash-window rejection, and preservation of unrelated historical bytes.
- Independent reader review found and reproduced the EOF/rotation lost-row race before deployment. The corrected race test counts both rows and exactly one rotation. Final review against the native writer found no remaining blocker for the managed 256 MiB/two-previous-files configuration.

One private CPU helper-cost comparison used 400 tracks with 40-point trails and 30 warmed calls per method. Median full display snapshot cost was 30.446 ms; the new health projection was 0.018376 ms. This is a helper microbenchmark, **not** an end-to-end API latency, model throughput, or GPU speed claim.

## Actual C++ writer to Python reader integration

A separate temporary CPU harness compiled the actual `rolling_output.hpp` into a small command-driven C++ writer and imported the actual `soak.FrameTail`. It wrote 24 monotonic observations to a private temporary family using a 600-byte cap and two previous files, polled after each group of three observations, and destroyed/reopened the writer after observation 11. Thus the check consumed real C++-generated files and manifests rather than a Python imitation of rotation.

Result:

```json
{"status":"pass","frames":24,"rotations":11,"writerGeneration":"12","writerReopenedAtGeneration":6,"sequenceGaps":0,"sessionChanges":0,"clockRollbacks":0,"backwardPts":0,"maxBytes":600,"retainedFiles":2,"retainedSizes":[203,406,406],"pollBatchFrames":3}
```

The executable was compiled with `g++ -O2 -std=c++17 -Wall -Wextra -Werror -Iservices/rtvi/rt-cv/smart-city/src`; both writer and reader used only a new `TemporaryDirectory`. No real live log family was opened. The complete reproducer is included below because its original `/tmp` location is ephemeral.

## Qualification limits

- This note records the new code/CPU review. Post-deployment detector, processed-preview, production UI, concurrent Ask, and sustained-run evidence belongs to the coordinator's separate receipts; it is not inferred from these tests. The earlier two-hour replay qualification applies to its recorded build and does not automatically qualify this changed build.
- Crash/interruption recovery intentionally stops for review when the log family is ambiguous or ends in a partial record. The writer does not silently discard bytes to make startup succeed.
- Per-source SQL history row limits are maintained at the existing 32-write cadence; a short overshoot between passes is possible. The 256 MiB history quota measures serialized frame payload, not the SQLite database/WAL file allocation.
- The visible raw-log cap covers the new managed live family. Existing evidence files are preserved and still occupy disk. Finite qualification output remains unchanged and must be planned separately.
- Source-frame-exact preview pairing does not establish absolute browser latency or validate source RTCP wall-clock accuracy. No new accuracy, VLM counting, calibrated multi-camera map, MV3DT, Thor, final Isaac city, full-booth-day, or continuous visitor-rate claim is made here. Existing limits remain in [the as-built record](../../smart-city-as-built.md).

## Source hashes reviewed

| File | SHA-256 |
| --- | --- |
| `apps/city/engine.py` | `739f358fc381dd146d0287187049fc95fe6b7a1ced54002c4867db8d0f6baa44` |
| `apps/city/main.py` | `0c74eaa927a2c326978c1dc8b06df6e6563f3189deaffa4ce85d271e1daf290e` |
| `apps/city/store.py` | `e21623d8aa6372f18073f89160d6301490876d4888384a5d5dba41c84f68aec9` |
| `tools/smart-city/controller.py` | `a3c0b4c95c0da230bfa7811e331b7d603e60f07ed7c6619331ccd8f71b0981e8` |
| `tools/smart-city/manage.py` | `8b9d59e51c00c49e61039b6a2129fac1b163639d35ae0d990b88152fbd7f7615` |
| `src/city_worker.cpp` | `f222cb672d8b53c1b9db48b445a827acf9f1efa22d1dc93205eb31d07dff8569` |
| `src/analytics_config.hpp` | `c1272c7ef05392540d33853e365c0041229b79441e09521384f2474e9124ea9d` |
| `src/rolling_output.hpp` | `2e64d261b4d499319ebe11c318e5bb318a597827d8ec040f578f57a674cbb07d` |
| `tools/smart-city/soak.py` | `53367510c4b96a3a418244ad7681000ea2b74e286dcdd987d08fb42ca4266816` |

The `apps/city` paths above are under `services/analytics/behavior-analytics`; native `src` paths are under `services/rtvi/rt-cv/smart-city`.

## Cross-language reproducer

Save the following as a temporary `.py` file and run it with the CPU test environment above. It creates and removes only its own temporary writer source, executable, and observation family. Adjust `ROOT` for another checkout.

```python
from pathlib import Path
import importlib.util
import json
import select
import subprocess
import tempfile

ROOT = Path('/home/sparkdev/vss')
spec = importlib.util.spec_from_file_location('polish_soak', ROOT / 'tools/smart-city/soak.py')
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)
CPP = r'''
#include "rolling_output.hpp"
#include <iostream>
#include <memory>
#include <sstream>
int main(int argc,char** argv) {
  if(argc!=2)return 2;
  const std::string path=argv[1];
  std::unique_ptr<city::RollingOutput> out;
  auto reopen=[&]{out.reset();out=std::make_unique<city::RollingOutput>(path,600,2);};
  reopen();std::cout<<"ready "<<out->generation()<<std::endl;
  std::string command;unsigned seq=0;
  while(std::cin>>command) {
    if(command=="reopen")reopen();
    else if(command=="write") {
      std::cin>>seq;std::ostringstream row;
      row<<"{\"siteId\":\"rotation-cpu\",\"sourceId\":\"camera\",\"sourceSessionId\":\"cpu-session\","
         <<"\"sequence\":\""<<seq<<"\",\"rawSourcePtsNs\":\""<<seq*1000000ULL
         <<"\",\"sourceTimeNs\":\""<<1700000000000000000ULL+seq*1000000ULL
         <<"\",\"timestampBasis\":\"source-rtcp\",\"objects\":[]}";
      out->write_record(row.str());
    } else if(command=="quit")break;
    else return 3;
    std::cout<<"ok "<<out->generation()<<std::endl;
  }
}
'''
with tempfile.TemporaryDirectory(prefix='vss-city-polish-cross-') as directory:
    directory = Path(directory)
    source = directory/'writer.cpp'; binary = directory/'writer'; path = directory/'live-observations.ndjson'
    source.write_text(CPP)
    subprocess.run(['g++','-O2','-std=c++17','-Wall','-Wextra','-Werror',
                    '-I'+str(ROOT/'services/rtvi/rt-cv/smart-city/src'),str(source),'-o',str(binary)],check=True,timeout=30)
    process = subprocess.Popen([str(binary),str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    tail = None
    def response():
        assert select.select([process.stdout],[],[],5)[0], 'writer response timeout'
        line = process.stdout.readline().strip();assert line, process.stderr.read()
        return int(line.split()[1])
    def command(text):
        process.stdin.write(text+'\n');process.stdin.flush();return response()
    try:
        assert response()==1
        tail = soak.FrameTail(path,['camera'],'rotation-cpu',start_at_end=False)
        generations=[];reopened=None
        for sequence in range(24):
            generation=command('write '+str(sequence));generations.append(generation)
            if sequence%3==2:
                actual=tail.read()['camera']
                assert actual['frames']==sequence+1, actual
                assert actual['sequenceGaps']==actual['clockRollbacks']==actual['backwardPts']==actual['sessionChanges']==0, actual
                assert actual['lastSequence']==sequence, actual
            if sequence==11:
                reopened=command('reopen');assert reopened==generation
        actual=tail.read()['camera']
        manifest=json.loads(Path(str(path)+'.manifest.json').read_text())
        assert actual['frames']==24 and tail.rotations==generations[-1]-1
        assert len(manifest['files'])==3
        sizes=[(directory/item['name']).stat().st_size for item in manifest['files']]
        assert all(size<=600 for size in sizes), sizes
        process.stdin.write('quit\n');process.stdin.flush()
        process.communicate(timeout=5);assert process.returncode==0
        print(json.dumps({'status':'pass','frames':actual['frames'],'rotations':tail.rotations,
                          'writerGeneration':manifest['generation'],'writerReopenedAtGeneration':reopened,
                          'sequenceGaps':actual['sequenceGaps'],'sessionChanges':actual['sessionChanges'],
                          'clockRollbacks':actual['clockRollbacks'],'backwardPts':actual['backwardPts'],
                          'maxBytes':600,'retainedFiles':2,'retainedSizes':sizes,'pollBatchFrames':3},sort_keys=True))
    finally:
        if tail:tail.close()
        if process.poll() is None:process.kill();process.communicate(timeout=5)
```
