# Tokenizer audit — October 22, 2026

The loaded tokenizer matches the official runtime tokenizer. Switching to the
tokenizer files bundled in the Moondream 2 repository would introduce a
mismatch, rather than resolve the current segmentation behavior.

Evidence is saved in [tokenizer-audit.json](tokenizer-audit.json).

- The cached Starmie tokenizer's computed Git blob hash is
  `b34d2539188d02eda1a1a23a1ec575349fb12518`. It exactly matches the public
  `moondream/starmie-v1/tokenizer.json` at revision
  `35192e10a54e36eabe0a7cc57a2c1aab371cafc5`.
- Its vocabulary has 51,200 entries. `segment` encodes to `[17374]`, while
  `detect` encodes to `[7235, 476]`, exactly as Photon's task templates specify.
- No tokenizer postprocessor, padding or truncation is configured. Tokenizing
  the object text does not silently add an EOS or answer separator.
- Official current MD2 and Preview `moondream.py` both explicitly load
  `moondream/starmie-v1`. MD2's repository also retains a different, older
  tokenizer/config with EOS 50256; it is not the tokenizer selected by that
  runtime. Photon correctly uses Starmie's EOS 0.
- SVG commands `M`, `L`, `C` have IDs 65, 64 and 55. They exceed the parser's
  special-token cutoff of 20. An encoded SVG example, followed by EOS 0,
  successfully passes the installed SVG decoder and becomes
  `M 0 0 L 1 0 L 1 1 Z`. Its path is not discarded by vocabulary filtering.

One meaningful prompt difference remains explicit: `metal panel` encodes as
`[37014, 11107]`, while ` metal panel` encodes as `[4774, 11107]`. Similarly,
`person` is 5974 and ` person` is 1102. Segment and Detect currently choose
different leading-space conventions. This is a task-template question, not a
different tokenizer. Separate inference diagnostics are needed to determine
whether the convention changes model behavior.

This audit imported only the tokenizer library and the standalone SVG utility;
it did not import PyTorch, initialize CUDA, load models, or change services.

Primary sources: [Starmie tokenizer](https://huggingface.co/moondream/starmie-v1/tree/35192e10a54e36eabe0a7cc57a2c1aab371cafc5),
[MD2 runtime](https://huggingface.co/vikhyatk/moondream2/blob/5d6c926f44e26b07957b0dd315bbedcb4c17a5fe/moondream.py),
[Preview runtime](https://huggingface.co/moondream/moondream3-preview/blob/5112966d1a723413b1c9a1e8bea272b72e647b35/moondream.py).
