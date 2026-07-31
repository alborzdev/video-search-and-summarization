# VSS Claw — OpenClaw Plugin

> **Note:** OpenClaw is the upstream framework name; the NemoClaw branding refers to the NVIDIA-curated skill bundle on top of OpenClaw.

NVIDIA Video Search & Summarization agent for [OpenClaw](https://github.com/openclaw/openclaw). The package stages the repository's complete VSS skill set at pack time, so the OpenClaw bundle stays aligned with the checkout rather than maintaining a second, stale skill list.

---

## Prerequisites

The following must be in place before VSS can deploy containers. The agent will check and guide you through each one via the `vss-prerequisites` skill — this is just a quick reference.

| Requirement | Min version | Install guide |
|---|---|---|
| NVIDIA GPU driver | 580+ | [nvidia.com/drivers](https://www.nvidia.com/en-us/drivers/) — reboot after install |
| Docker Engine | 28.3.3 | [docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/) |
| Docker Compose | v2.39.1 | Included with Docker Desktop / Engine |
| NVIDIA Container Toolkit | latest | [docs.nvidia.com/datacenter/cloud-native/container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) |
| NGC API key | — | [ngc.nvidia.com](https://ngc.nvidia.com) → Setup → API Keys |

**Post-Docker install:** add your user to the docker group so containers run without sudo:

```bash
sudo usermod -aG docker $USER && newgrp docker
```

Once OpenClaw is running, ask the agent to use `vss-deploy-profile` to check prerequisites for the profile you want to deploy.

---

## 1. Install OpenClaw

```bash
npm install -g openclaw
```

Verify the install:

```bash
openclaw --version
```

---

## 2. Install the VSS Claw Plugin

**From the cloned VSS repo:**

```bash
openclaw plugins install ./video-search-and-summarization/.openclaw/
```

**From npm (after publishing):**

```bash
openclaw plugins install @nvidia/openclaw-vss
```

On first gateway start after install, the plugin automatically copies workspace templates (`BOOTSTRAP.md`, `IDENTITY.md`, `SOUL.md`, `AGENTS.md`, `TOOLS.md`) to `~/.openclaw/workspace/` and patches the gateway service for Docker group access.

---

## 3. Verify

```bash
openclaw skills list | grep -E "ngc|vss"
```

Expected output includes the VSS skills shipped by the current checkout. For VSS 3.2.1 that is:

```
vss-ask-video
vss-deploy-dense-captioning
vss-deploy-detection-tracking-2d
vss-deploy-detection-tracking-3d
vss-deploy-profile
vss-deploy-video-embedding
vss-generate-video-calibration
vss-generate-video-report
vss-generate-video-report-rag
vss-manage-alerts
vss-manage-video-io-storage
vss-query-analytics
vss-search-archive
vss-setup-behavior-analytics
vss-setup-video-analytics-api
vss-summarize-video
```

---

## 4. First Run

Start a new OpenClaw session. The BOOTSTRAP flow runs automatically and the agent will introduce itself and walk through initial VSS configuration.

---

## Skills Reference

| Skill | Trigger phrases |
|---|---|
| `vss-deploy-profile` | "deploy VSS", "check profile prerequisites", "start search/lvs/warehouse" |
| `vss-search-archive` | "search archived video", "ingest this video for search" |
| `vss-summarize-video` | "summarize this recorded video" |
| `vss-manage-alerts` | "create an alert", "monitor incidents", "notify OpenClaw" |
| `vss-ask-video` | "what happened in this clip?" |
| `vss-query-analytics` | "show analytics metrics/incidents" |

The Skills tab is the source of truth for the full installed list; each skill's `SKILL.md` owns its trigger boundary and workflow.
