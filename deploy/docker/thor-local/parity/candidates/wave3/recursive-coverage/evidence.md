# Recursive coverage evidence

Capture date: 2026-07-31

Documentation target: NVIDIA VSS 3.2.1

Reviewed upstream revisions:

- VSS 3.2.1 GA commit: `7640d917047cf7b0fd3085eefb8282754b56bc94`
- Reviewed upstream `main`: `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`

## Canonical evidence

| Evidence | SHA-256 |
| --- | --- |
| 172-URL set including index | `74a1d6ae1f520049202e47dce69fa56d10c28c48aa3aa24a3a2c4214dad4b208` |
| 171-URL set excluding index | `e95857861e5ace82021bf49c99c74dd0c9861b6cefc3a6e1606022505fed7616` |
| Added 19-descendant set | `85281ae9b39c548abda6fdea578953726feca2fe829479fb7a63d24cc51ddf25` |
| 26,449 directed URL-pair edge set | `58759d1dc9b060c90518aa2928190381d2838558d170746e9af783a0dbc35a55` |
| `recursive-targets.json` file | `30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa` |
| `crawl-graph.json` file | `7f8fff1f1a540afe8663e461b687eeb24ba8b229f2d867d4bcf18ff83a157f99` |
| `recursive-coverage.json` file | `64873383117a54f75650f979a99cbec67221adbfaf41ef7e9fd3719825aba99b` |

Canonical collection hashes use compact, key-sorted JSON serialization with
ASCII escaping. URL sets are sorted arrays. The edge set is a sorted array of
`[source_url, target_url]` pairs.

## Bound repository inputs

| Input | Count | SHA-256 |
| --- | ---: | --- |
| Direct-index targets | 152 | `825cbcfd90f7aa8c35290c7eb179f2e6af4775bc192ef5b3f7763559b7fd2850` |
| Direct-index coverage | — | `562d85e973557c7351955fc043dafc29038b6dea39458db8a6453c5c889bc29d` |
| Live official source ledger | 55 sources / 161 capabilities | `e33eff2cc03f7770e0513a061732ec860ccb241721e40b9d60d6dbb2b0dafee8` |
| Agent Smart City candidate | 40 documentation sources | `7b544d9aa3d74ab1935f44647026fa4ff85c1dacee3d1c284aa52269bfdca395` |

None of the 19 added descendants occurs as a source in the bound live ledger.
All 40 Agent Smart City documentation sources occur in the recursive set.

The Agent Smart City candidate contains the corrected pages
`smartcity-docs/License-Information.html` and
`smartcity-docs/Troubleshooting-Guide.html`. It does not contain the stale 404
paths `smartcity-docs/License.html` or `smartcity-docs/Troubleshooting.html`.

## Review conclusion

The direct index is not a complete documentation denominator. Recursive closure
adds 19 Warehouse pages: eight substantive semantic omissions, nine optional
external-workflow dependencies, and two navigation/reference hubs. This evidence
does not claim that a reachable page is implemented locally; it identifies the
complete version-scoped documentation surface that subsequent parity candidates
must classify and, where applicable, implement or qualify.
