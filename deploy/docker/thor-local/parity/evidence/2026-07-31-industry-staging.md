# Thor industry-lane staging evidence — 2026-07-31

This checkpoint records artifact availability only. It does not claim that the
Smart City, warehouse, MV3DT, or calibration lanes have passed runtime
qualification.

The protected Thor NGC credential was used through a temporary Docker client
configuration. The session was logged out after the pulls and the temporary
configuration contains no registry authorization entry. The global Docker and
NGC client profiles were not modified.

## ARM64 images staged locally

| Image | Local content-addressed digest |
| --- | --- |
| `nvcr.io/nvidia/vss-core/vss-configurator:3.2.1` | `sha256:35e3e31e7d9e62b298d6dbcb91244d54b0686845227f26e46f886493e9fe4504` |
| `nvcr.io/nvidia/vss-core/vss-vios-nvstreamer:3.2.1` | `sha256:7074784d32f996734ef091405f14965573d40257d843bba29d7ca2ef36f58e4d` |
| `nvcr.io/nvidia/vss-core/sdr-mw-l:3.2.0` | `sha256:7f98d296295a60ccd59c23b4c23ff0c72bfa01a669279c43896ed8d196f14069` |
| `nvcr.io/nvidia/vss-core/vss-rt-config-adaptor:3.2.0` | `sha256:f7967b26377313fe0131c251ae203f70b9743b3edf61fa5b68d21f822dbbb340` |
| `nvcr.io/nvidia/vss-core/vss-rt-cv-mv3dt-bev-fusion:3.2.0` | `sha256:b5286d97e82095c12ed90ca5ec9486ce2bf8897819fc1e995b0b9e166378265d` |
| `nvcr.io/nvidia/vss-core/vss-auto-calibration-ui:3.2.1` | `sha256:e86c16ac9e88241dabd35e6f44c2d5086a77551a3e3654b4905e51bbf4cdf6a4` |

`docker image inspect` reports `arm64` for every image above.

## Available but deliberately not pulled

NGC publishes an ARM64 manifest for
`nvcr.io/nvidia/vss-core/vss-auto-calibration:3.2.1`, but its compressed image
size is 14.07 GB. With 80 GB free after staging the smaller lane images, it was
not pulled in this checkpoint so the host retained a conservative build and
extraction margin. This is a separate auto-calibration staging gap, not a
warehouse sample-data requirement.

## Optional NVIDIA reference fixture (not a parity gate)

The protected credential receives HTTP 403 for
`nvidia/vss-warehouse/vss-warehouse-app-data:3.2.0`. The repository does not
currently contain the warehouse RT-DETR/Sparse4D/BodyPose model bundle or the
official warehouse sample videos.

That roughly 100 GB resource is excluded from the Thor parity target. Its 403
does not block warehouse capability or acceptance: the supported acceptance
path is operator-provided compatible models, videos/streams, and calibration.
The current Thor warehouse work proves only the custom-data layout and static
Compose/preflight contract; no warehouse runtime qualification is claimed by
this checkpoint.
