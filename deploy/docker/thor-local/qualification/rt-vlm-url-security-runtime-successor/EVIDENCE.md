# Evidence

- Live API: ready; `/v1/generate_captions` uses `VlmQuery` with `url` and `url_headers`; loopback SSRF input returned HTTP 422.
- Runtime identity: exact VSS 3.2.1 RT-VLM arm64 image and current Thor `asset_manager.py` SHA-256.
- Request auth: allowed Authorization delivered over HTTPS; Host, X-Forwarded-For, and Transfer-Encoding overrides blocked.
- Environment auth: delivered only to the configured exact domain and absent on an unmatched domain.
- Transport boundary: Authorization removed over plain HTTP, retained on a same-host redirect, and removed on a cross-host redirect.
- Redirect range: zero hops rejected immediately; one hop rejected a second redirect; two hops completed; negative values clamped to zero; values above ten clamped to ten.
- Redirect security: the two-hop success invoked the bounded SSRF validator for the initial URL and both targets.
- Size: default 8 GiB parsed; a 30-byte fixture passed a 64-byte configured limit; a 96-byte response produced `FileTooLarge`/413 and was not saved.
- TLS: self-signed certificate rejected by default; listed domain downloaded successfully; unlisted domain retained verification and was rejected.
- Exit integrity: the disposable released-image process exited zero without OOM or restart.
- Cleanup: disposable container and certificates absent; main RT-VLM container and asset catalog exact.

No raw credential, request UUID, downloaded media, or certificate is retained.
All fixture traffic stayed on loopback. No VSS Agent generation, external
request, image/model download, RT-CV/VIOS mutation, or Warehouse sample occurred.
