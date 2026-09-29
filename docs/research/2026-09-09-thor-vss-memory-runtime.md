# Thor VSS memory/runtime research — 2026-09-09

Read-only investigation; no runtime, driver, or service changes. The objective is simultaneous local availability of the complete VSS graph within 122.824 GiB, with spare memory for actual requests. This note provides experiments to qualify, not a claim that the graph is already stable.

## Confirmed platform findings

This host reports R38.4.0 in `/etc/nv_tegra_release`. NVIDIA's matching release notes list issue **5661165**: memory may remain high after vLLM/SGLang or their containers stop; the documented workaround is `sync` followed by `vm.drop_caches=3`. Issue **5699079** says excessively large CUDA allocations can reboot the device, recommends avoiding allocations exceeding physical memory, and suggests raising CUDA-process OOM scores so system processes are less likely to be killed. These are actual R38.4 known issues, not speculation based on model size. The notes do not promise that a particular memory reserve prevents all freezes. [NVIDIA R38.4 release notes, page 10](https://docs.nvidia.com/jetson/archives/r38.4/ReleaseNotes/Jetson_Linux_Release_Notes_r38.4.pdf).

Our earlier controlled `drop_caches=2` recovered 22.913 GiB with essentially unchanged file cache and only ~1.2 GiB less slab. This establishes reclaimable kernel-held memory; it does not measure any individual NVIDIA pool. See [local measurement report](../../artifacts/thor-memory-2026-09-09/REPORT.md). Linux documents 2 as reclaiming reclaimable slab objects, 3 as also dropping clean page cache, and cautions that repeated cache dropping can impose substantial I/O/CPU cost. A boundary cleanup after stopped models is more defensible than a periodic cleaner competing with workloads. [Linux vm sysctl documentation](https://docs.kernel.org/admin-guide/sysctl/vm.html#drop-caches).

NVIDIA's current OpenRM source defines `EnableSystemMemoryPools` default `0x211` (decimal **529**), enabling 4 KiB, 64 KiB and 2 MiB page pools that retain freed memory to accelerate later allocation. This exactly matches the observed parameter. [NVIDIA nv-reg.h](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/main/kernel-open/nvidia/nv-reg.h). Its `nv-vm.c` registers `nv-sysmem-alloc-node-…-order-…` shrinkers, counts retained pages and returns clean/dirty pooled pages to Linux during scans. [NVIDIA nv-vm.c](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/main/kernel-open/nvidia/nv-vm.c). This is strong mechanism evidence, with a version caveat: upstream **580.95.05** files examined do not contain these pool definitions, while mutable main does; neither is an exact source attestation for the installed Thor **580.00** build. Do not disable driver pools or replace modules based solely on this comparison.

## Freezes: distinguish a symptom from its cause

A May 2026 firsthand Thor R38.4 report describes persistent `nvfancontrol`/thermal-worker D states at `tegra_bpmp_transfer`, reproduced with standalone managed-memory CUDA pressure. Its vLLM image digest matches our Nemotron image, and it reports vLLM 0.19.0+cu130. NVIDIA suggested a known Orin host1x IRQ-lock patch; the reporter said it did not fix Thor. **The final report says a clean reinstall eliminated the fault.** NVIDIA's own candidate was an R-state transient with working thermals, not the same persistent D-state failure. This is a diagnostic lead, not a confirmed universal Thor bug, a validated patch, or proof of our root cause. [Full NVIDIA forum thread, particularly posts 8–13](https://forums.developer.nvidia.com/t/370477).

NVIDIA support explains in a separate firsthand Thor case that watchdog reset indicates the system was already unresponsive; the reset is a consequence and can follow storage/WLAN faults too. It is not an OOM diagnosis. [NVIDIA support response](https://forums.developer.nvidia.com/t/370613/8).

For our experiments, persist host MemAvailable, swap, memory PSI, container stats, process states, kernel warnings, and request outcomes. Inspect persistent D-state stacks if they appear; do not treat every transient devfreq observation as a deadlock. If thermal readers begin blocking, avoid accumulating more blocked monitoring processes. A new hang despite ample measured headroom should redirect investigation to BSP/install/runtime health, not automatically trigger another tighter memory attempt.

## Existing controls and remaining low-memory options

The source contract uses exact Nemotron 3 Nano 4B FP8 and Cosmos3 Nano BF16 identities from NVIDIA VSS 3.2.1; the older Edge 4B repository is not interchangeable. [Official VSS 3.2.1 edge documentation](https://docs.nvidia.com/vss/3.2.1/edge-deployment.html), [local exact-model contract](../../deploy/docker/thor-local/official-edge/README.md).

| Control | Effect and test constraint |
|---|---|
| Explicit KV bytes | vLLM supports a fixed cache allocation; it overrides utilization-based KV sizing. It bounds KV, not all runtime allocations. |
| Smaller context and sequence count | Restricts capacity needed for admitted requests. Reducing context alone does not necessarily shrink an already fixed cache allocation. |
| Eager mode | Removes CUDA graph capture allocations, trading throughput for lower memory. |
| Lower batched-token budget | Bounds prefill work and can reduce activation peaks; verify long prompts still progress with chunked prefill. |
| Disable multimodal processor cache | Avoids retained preprocessed media; trades repeated processing for memory. Cache can be duplicated across API/engine processes. |
| FP8 KV | Potential cache reduction at equal token capacity, separate from FP8 weights. Requires installed-backend/model support and output-quality validation. At fixed KV bytes it increases capacity rather than automatically saving memory. |

These vLLM semantics are documented in [vLLM CLI reference](https://docs.vllm.ai/en/v0.11.2/cli/serve/) and [v0.19 memory guidance](https://docs.vllm.ai/en/v0.19.0/configuration/conserving_memory/). Verify actual installed engine arguments instead of assuming current documentation matches both containers. CPU offload consumes the same physical DRAM on Thor and is not extra capacity; it is therefore not a primary strategy for total-RAM reduction.

The [RT-VLM wrapper](../../services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py) already forwards `VLLM_KV_CACHE_MEMORY_BYTES`, `VLM_MAX_MODEL_LEN`, `VLLM_MAX_NUM_BATCHED_TOKENS`, eager mode, prefix-cache and processor-cache settings. It checks the installed `AsyncEngineArgs` signature and **warns and ignores an unsupported KV-byte setting**. Validate startup logs or effective engine config. `max_num_seqs` comes from `_max_batch_size`; `VLM_BATCH_SIZE=1` matters, not merely an arbitrary `VLLM_MAX_NUM_SEQS` variable. This wrapper does not currently forward a generic `VLLM_KV_CACHE_DTYPE` setting.

Current [Cosmos overlay](../../deploy/docker/thor-local/official-edge/compose.yml) has 4 GiB KV, 16K context, one process/sequence, 4096 batched tokens and eager mode. Its recorded minimum KV for one 16K request is about 2.25 GiB, so **3 GiB** is a reasonable isolated trial, subject to observed engine acceptance and real-media requests. Its BF16 weights alone were observed around 16.7 GiB; shrinking KV cannot eliminate that floor. Current [Nemotron demo command](../../deploy/docker/thor-local/official-edge/thor_demo.py) uses eager and 0.12 utilization but has no explicit context, sequence or KV-byte bound. An isolated explicit-cache/single-sequence trial has more deterministic budgeting than simply decrementing the fraction. Start with the exact model's configured/required context and measure tool-call prompts before selecting a smaller cap.

## Practical acceptance sequence

1. Measure each model alone at startup, first real request, repeated requests, and after stop/reclaim. Record maximum total host commitment, not only steady idle usage.
2. Preserve exact artifacts while trying smaller fixed KV allocations, one sequence, eager execution, bounded prefill and media caches. Make only one change at a time so savings and breakages are attributable.
3. Budget remaining CV/embedding/video-decoding services from their measured active workloads. Add individually; startup peaks can exceed steady state.
4. Only after isolated measurements justify a new cumulative budget should the separate combined topology be admitted. Preserve the old dual-model safety lock until a new qualified launch path exists.
5. Validate repeated file summarization, search ingestion/retrieval, Agent tool calls, and a bounded live source. Check memory after successive jobs to distinguish retained sessions from stable caches. An earlier firsthand VSS/Cosmos-Reason2 case traced growth to retained chat sessions (`enable_chat=True`); disabling chat stopped growth for that reporter. This is a test hypothesis for our different version/model, not an established current defect. [Original report and resolution](https://forums.developer.nvidia.com/t/361511/4).

No source establishes a universally safe reserve or guarantees that current exact dual-model VSS will fit reliably. The answer must come from measured peaks and stable repeated workloads on this host. A driver/BSP upgrade or reinstall is a separate maintenance decision if runtime faults remain after bounded allocation; it should not be smuggled into memory tuning.
