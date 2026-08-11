# Evidence

`runtime-receipt.json` is the sanitized retained current-Thor execution record. It is produced only after both positive semantic oracles, every adjacent-negative security oracle, exact cleanup, source-lock verification, and receipt-schema validation pass.

The receipt intentionally retains only booleans, counts, HTTP statuses, stable digests, and bounded policy facts. It excludes prompts, semantic output, raw resource/request/container identities, credentials, and fixture bytes.
