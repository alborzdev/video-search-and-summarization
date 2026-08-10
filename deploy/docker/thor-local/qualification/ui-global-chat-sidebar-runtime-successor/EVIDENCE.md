# Evidence

On 2026-08-10, target commit
`d16797d05490c169fd600bd653084f7e7968da0f` passed the Global Chat sidebar
runtime harness on Thor.

- The exact deployed profile exposed Search, Alerts, Dashboard, and Video
  Management while the legacy Chat and Map tabs remained disabled.
- Global Chat was open by default, collapsed and reopened with session-state
  persistence, and clamped to one-third and two-thirds of the available width.
- Dark-to-light-to-dark theme switching rendered correctly.
- New chat, new folder, retained folder state, endpoint settings, all four
  WebSocket schema choices, and the intermediate-step toggle passed.
- Every chat-video input accepted MP4 and MKV; the user-facing drop zone was
  visible and the MIME aliases were present.
- Three visible Video Management `+ Chat` actions were found. One click created
  exactly one context chip, changed the action to `Added`, raised the collapsed
  unseen indicator, cleared that indicator when opened, and removed the chip
  cleanly.
- An isolated one-key profile response proved legacy Chat and the global
  sidebar coexist: legacy Chat rendered on its tab, while the global sidebar
  rendered on Search.
- A two-row Alerts fixture offered exactly one `Generate Report` action for the
  valid incident and suppressed it for the adjacent fallback-ID incident.
- The compiled report frame used `user_message` plus `chat_stream`, contained
  one user message, and was captured exactly once while the real send count
  remained zero.
- The live current-profile and report contexts recorded no console warning or
  error hashes, page errors, failing HTTP responses, or non-loopback responses.
- The synthetic one-key profile override recovered only through the reviewed
  React hydration codes 418 and 423; no other page error was admitted.
- The run used 24 browser actions and 114 loopback responses in 11.156 seconds,
  below its 40-action, 1,200-response, and 180-second bounds.
- The UI, HAProxy ingress, and VIOS ingress image identities, start times,
  health, restart counts, and OOM states matched exactly before and after.
- All three contexts and the browser closed, all screenshots were deleted after
  hashing, and no server-side resource or configuration changed.
- The Warehouse sample bundle was excluded.

The retained receipt SHA-256 is
`6a431d7a3b9c025ff158db9817265a96332cdcff7298d37ca0173a7ad673a743`.
The canonical oracle SHA-256 is
`c78210466c5089cbd4c818ea360ba91c14eee9037f2422547902ab74fee11687`.
The official evidence SHA-256 is
`cdda66a198192335c1bbc9e59cdb907a8084e3ff9590c62388c1926e23e3357f`.
