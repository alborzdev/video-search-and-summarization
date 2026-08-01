# Thor host-preflight observation — 2026-07-31

This is a read-only admission observation, not VSS feature runtime evidence.
The explicit `inspect` mode executed its 14 fixed informational commands and
read eight fixed host files. It performed no Docker lifecycle operation,
network request, credential access, download, or host mutation.

Observed result: `blocker`; runtime qualification was not started.

Passed admission facts:

- NVIDIA Jetson AGX Thor, AArch64;
- Jetson Linux BSP 38.4 and NVIDIA driver 580.00;
- Docker client/server 29.2.1, Compose 5.0.2, NVIDIA Container Toolkit 1.18.0;
- NVIDIA runtime present;
- required kernel socket/map limits and the cache cleaner passed.

Current blockers and warnings:

- 33,988,694,016 of 131,881,062,400 memory bytes were available
  (`0.257722`), below the official-edge `0.80` admission threshold;
- Docker reported the `systemd` cgroup driver and daemon configuration did not
  contain `native.cgroupdriver=cgroupfs`;
- the current Nemotron/Cosmos official-edge artifact lock remains
  `incomplete_fail_closed`, and the exact locked vLLM image is absent;
- ports 8000 and 8001 were occupied by the existing local model workloads;
- 64,983,867,392 bytes were free on `/`, below the 150 GiB warning threshold;
- 29 existing container records matched the conservative VSS/MDX conflict
  rules; most are stopped historical containers, while the prepared Qwen VLM
  and existing local model workload still require operator-aware scheduling.

The exact locked RT-VLM image identity was present, but artifact filesystem
trees were deliberately not scanned by this preflight. The separate
official-edge audit remains required after exact model paths are staged.
