# Remaining advertised-entry candidate evidence boundary

This is reviewed planning evidence only. The authoritative current coverage
ledger reports 500 advertised strings: 289 exact mappings and 211 semantic
blockers. This package partitions every blocker once and proposes the exact
candidate capability and future oracle semantics needed to remove that
inventory gap.

The candidate rows do **not** prove that any feature works on Thor. A future
successor must merge and schema-check the rows into the official capability
ledger, regenerate one full planning-index oracle per capability, and preserve
all runtime states and evidence. Later, separately authorized runtime work must
materialize fixtures, executors, observations, adjacent negatives, and cleanup
receipts before any local feature can become `passed_current`.

Locked current inputs:

| Input | Raw SHA-256 |
| --- | --- |
| manifest | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` |
| official capabilities | `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0` |
| official capability schema | `fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896` |
| capability oracles | `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90` |
| advertised gap plan | `2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c` |
| global advertised-entry coverage | `2ea517799c03bcc432856a805b8e35ae1d97c8c3dd2f7b928d99004bbb7b6af5` |

Package locks:

| Artifact | Raw SHA-256 |
| --- | --- |
| features 0–9 tranche | `308ed1cb659eac258ff0271c4b46e1054e50b0f7e04e8c6ba6da622b63e13707` |
| features 10–18 tranche | `d11a65f518973d33796db8ad53a0324853d574d23e424692293c3b659de39097` |
| features 19–35 tranche | `1d91699fd3cfd4ac651be82c5e88fc78357c3ab683d1810de4c73c8e89623fae` |
| candidate schema | `e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8` |
| compiled candidate | `a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd` |

Compiled candidate payload SHA-256:
`31ab6971f9e447cc772644a21a209ceda9980c0f863b6d13b109984721754b53`.

The optional Warehouse sample remains excluded and is not a candidate fixture.
Custom-data Warehouse capability remains in scope. All six external candidates
remain opt-in provider boundaries and cannot count as Thor-local evidence.
