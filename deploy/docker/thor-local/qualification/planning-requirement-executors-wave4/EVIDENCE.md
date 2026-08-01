# Evidence

- Live planning requirements still open before candidate-only Waves 3/4: **84**
- Integrated static-subset planning bindings: **26**
- Prior nonadvancing Wave 3 selections: **6**
- Previously unselected requirements at the Wave 4 baseline: **78**
- New isolated source cases: **6**
- Prior-case overlap: **0**
- Observed matches: **5**
- Observed mismatches: **1**
- Requirements deliberately left open: **72**
- Runtime evidence added: **0**
- Live acceptance/oracle changes: **0**
- Network, downloads, credentials, Docker, or lifecycle actions: **0**
- Warehouse sample used: **no**

The sole mismatch is `systems-alert-vlm-backends`: Qwen VL is present in the
locked capability contract but absent from `services/alert/README.md`. The result
preserves that absence as `missing=["Qwen"]`; it does not infer model availability
from another profile, a mutable image tag, or the separate Thor alternate lane.
