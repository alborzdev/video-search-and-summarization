# Evidence

The upstream fetch on 2026-08-02 resolved:

```text
refs/remotes/upstream/develop  8db763b4632864ec2875cef2004447d0f8bf1086
refs/tags/nightly-20260802    8db763b4632864ec2875cef2004447d0f8bf1086
parent                        a34c6b0406bcadd380e4c4dac6ff7e830deb27e5
tree                          223a9c8850eb92ca04208a88598b222283c2ea25
```

`git diff --name-status a34c6b040..8db763b46` returned exactly:

```text
M deploy/docker/industry-profiles/warehouse-operations/overrides.env
```

The old/new blobs are `e1b77dedc8329e22923a233e20751ee3c72d8b13`
and `5c96410077183a878db3d10df8006c81b934ba30`. The zero-context
unified diff SHA-256 is
`ab4e29eea8c0bb4b5937fc1828f43370bf4941858795e8b9cd0f5a39d7f6f7ed`.
Its only semantic change is adding `phoenix` between `vss-ui` and
`elasticsearch` in `COMPOSE_PROFILES_WH_2D`.

Appending the exact canonical path/status row to the frozen denominator yields
500 develop commits, 109,059 develop-side path records, sequence digest
`eb88608301f487d442b22a80dbc441871da7acd0c469f8857ff0745205169a2e`,
JSONL digest `f4859f64b68b7f0171dc246ccb12e24040994f0de22efc8ac81e1a5de3baf130`,
and deterministic gzip digest
`7a49036f4adf3ebece81b3eb94eb42702af3a90d035e8f5d3900625f672cf5a3`.

No deployed command was run. Evidence and promotions remain empty.
