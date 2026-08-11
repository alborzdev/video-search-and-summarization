# Evidence

Runtime evidence is generated only by the bounded executor after exact source,
fixture, runtime, transport, semantic, and cleanup checks pass. The retained
receipt contains hashes and boolean/classification oracles, never prompts,
model prose, request identifiers, credentials, or temporary asset identifiers.

The Warehouse sample bundle, VSS Agent `/generate`, stream mutation, and
service lifecycle actions are outside this qualifier.

The retained run passed in 4.819772 seconds. It made exactly ten loopback
RT-VLM API requests, two model calls, one host-side TLS fixture verification,
two temporary local-server requests, and three bounded container inspections.
Plain HTTP preserved the blue→green→red order; HTTPS returned the stable
animation classification after the exact 4,372,373-byte W3C fixture hash was
verified. Loopback SSRF and redirects were structured 422 rejections. The
catalog and asset statistics returned to zero and the local server stopped.

- Contract SHA-256: `575b553962a2bd7f1386d6308f9ce1b5e6a066d2c5ef35441f21a3af6b91f7af`
- Receipt schema SHA-256: `466c851fe84b50ba55bc35c7785e8f99c6078d219ce175c92391b708ade2971b`
- Receipt SHA-256: `70939dab6695c5e93e091c68ed1c30840555faf2450c39c3abd8fc3309a90d92`
