# Evidence boundary

Status: **exact-title inventory transition verified; non-advancing**.

The predecessor is anchored to commit
`76596ccd1a2b02644506399b7e27ce36bbe3544b`, its parent and root tree, six
source-object hashes, and plan payload `7a50b418…`. Current sources are locked
to six exact hashes and plan payload `93981c6e…`.

Independent reconstruction across all 500 advertised literals proves:

- predecessor compiler scope: 13 exact, 487 missing, 413 family-only;
- current scope: 289 exact, 211 missing, 137 family-only;
- exactly 276 newly recognized mappings, all existing non-`manifest-entry.*`
  capabilities;
- every new row has a byte-identical title, the same feature ID, and a bound
  oracle;
- all 289 capability and 289 oracle records are unchanged;
- the 74 scoped gap entries and their semantics are unchanged; only generated
  summary/source-lock/payload fields may differ;
- zero capability, oracle, or plan runtime evidence and zero current-pass
  promotion;
- Warehouse sample exclusion in the plan and every oracle execution bound.

The complete predecessor `tooling-entry-ledger-successor` is frozen by tree
OID `919048958e1ac0122636ddd8afa8f749d09eebdd` and seven file hashes. It is
identity-verified but not rerun against mutable current inputs.

`proof.json` is deterministic and strict-schema validated. Its mapping hashes
bind the ordered 289-row complete mapping and 276-row newly recognized subset
without presenting planning inventory as runtime evidence.
