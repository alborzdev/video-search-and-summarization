# Official VSS 3.2.1 RT-VLM model-table reconciliation

Authority reviewed on 2026-07-31:
<https://docs.nvidia.com/vss/3.2.1/real-time-vlm.html#supported-models>

The versioned NVIDIA documentation lists 18 exact `MODEL_PATH` values. The
byte-locked checkout README at upstream revision
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57` lists 11. The seven documentation-
only entries are:

- `ngc:nim/nvidia/cosmos-reason2-8b:hf-1208`
- `ngc:nim/nvidia/cosmos3-nano-reasoner:modelopt-fp8-final_format_fix`
- `git:https://huggingface.co/nvidia/Cosmos3-Nano-Reasoner`
- `ngc:nim/nvidia/cosmos3-super-reasoner:modelopt-nvfp4-full-quantize-final_format_fix`
- `ngc:nim/nvidia/cosmos3-super-reasoner:modelopt-fp8-final_format_fix`
- `ngc:nim/nvidia/cosmos3-super-reasoner:bf16-final`
- `git:https://huggingface.co/nvidia/Cosmos3-Super-Reasoner`

The exact 18-row oracle is
`deploy/docker/thor-local/rt-vlm/official-vss-3.2.1-models.json`, SHA-256
`872c986a19ef30dfdf9f71e6ab8c9e9cb80a847a096e4442e1579b65703affb7`.
The validator hard-codes that digest and authoritative release URL, checks the
checkout README separately, and rejects any count, ID, selector, order, note,
or skew change.

This evidence is documentation parity only. No missing model was downloaded,
no container was started, and no Thor runtime, memory, audio, or quality claim
is established for any of the 18 variants. All missing exact artifacts remain
`missing_exact_artifact_unqualified`.
