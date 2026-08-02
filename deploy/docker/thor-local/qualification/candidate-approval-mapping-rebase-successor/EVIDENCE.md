# Final static evidence

Status: final activation and protocol dependencies consumed; outputs generated
and exactly pinned.

## Versioned metadata inputs

| Input | Raw SHA-256 |
| --- | --- |
| Projected selector | `d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112` |
| Projected live-ready descriptor | `4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca` |
| Activation receipt | `93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e` |
| Activation receipt schema | `5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f` |
| Migration-rebase oracle registry | `911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021` |
| Migration-rebase oracle schema | `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233` |

The activation receipt is schema-validated and must bind both projected pair
paths/hashes plus the immutable descriptor locator.

## Explicit protocol transition

| Artifact | Historical lock | Final consumed lock |
| --- | --- | --- |
| Protocol candidate | `886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62` | `cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7` |
| Protocol schema | `831d982f6912358b8dfae049cd10ed709af299d91cb7196031d28b29a092877d` | `399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb` |

Final protocol compiler/test locks are
`87e3fb6b0894c09ad91b2494bf3e4c6838639d3659eba934ea8ea6183bc961af`
and `1503edfe00afe90e5eee95dfe7e5edc5225f6df19a92999ce6d6a1e1743c63cd`.
Its own check reports 7 preserved plus 23 planning cases, 30 bindings; 11 tests
and Ruff pass. Protocol candidate payload identity changes from
`65715e2ebfbe164ae38a6b20ca7dc23b6f3a65aaa9dd1632bdda746c4c929f24`
to `6667309aefc03eb410651bd11769301be77cc5d9baf40688fa0f75f5752a58d6`.

## Mapping preservation result

- Candidate order digest remains
  `1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9`.
- Candidate-row digest changes from
  `8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4`
  to `3b579c6abded078f2bc4ddd8fdca34f4f577171463c02f7ecca797ce2f2789ab`.
- Mapping-record digest changes from
  `93791e8b9d7b8ec3368ba78c1f55217498260bdb1c3f9777f0d3f6e5ab11c60c`
  to `9ec211afcabe645573a145c7a5e9dbaf5c030eab552da4add0698f15e33b2062`.
- 209 mapping rows are byte-identical. Two rows change only the three reviewed
  integrity fields; all 211 mapping semantics and zero-approval fields remain
  exact.

## Final outputs

| Output | Raw SHA-256 |
| --- | --- |
| `mapping.json` | `dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a` |
| `mapping.schema.json` | `41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5` |

Validation: 27 tests passed with zero skips; compiler check, Ruff, and diff
checks passed. Historical mapping package and canonical selector/descriptor
hashes remain equal to their immutable locks.

No runtime execution, network access, Docker access, warehouse sample bundle,
canonical mutation, or historical-package mutation occurred.
