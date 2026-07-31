# Official small AutoMagicCalib fixture lock

Date: 2026-07-31

The official AutoMagicCalib fixture was pinned independently from the excluded
warehouse sample bundle. Its source is commit
`0cfd2b790fd77598b0543340a65c2a0e1d192327` of
`NVIDIA-AI-IOT/auto-magic-calib`, path
`assets/sdg_08_2_sample_data_010926.zip`.

The external cached object is 160,499,115 bytes with SHA-256
`0dceb0cc8324f5775b0c2007efe7a3e7c36fda10c5964b88e20712b002d98bdb`.
It is not tracked in Git and is never extracted by the verifier.

The lock covers the exact ten-member outer ZIP: four MP4s, alignment JSON,
layout PNG, directories, and the nested ground-truth ZIP. It also covers the
two nested members and content oracles for four cameras, three alignment points
per camera, the 879x1308 layout, MP4 signatures, paths, types, modes, sizes,
compression, CRCs, and member hashes. Unsafe paths, links, encryption,
duplicates, archive drift, and content drift fail closed.

The connected stager uses the exact commit URL, a disk reserve, same-directory
temporary file, full verification, fsync, and atomic publication. Re-running it
against the verified cache is offline and idempotent.

Evidence collected:

- real offline verification returned `state=locked`, ten members, four videos,
  and `extracted=false`;
- 28 focused tests and the Thor auto-calibration wrapper passed;
- no partial download remained.

The protected AMC backend image and optional VGGT refinement model remain absent.
No AMC container or calibration job ran, so the feature remains runtime-blocked.
