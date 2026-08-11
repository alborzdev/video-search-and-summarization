# RT-Embed multimodal runtime successor

This package binds official capabilities 368 and 371 to current-Thor runtime
evidence. It proves that the local VSS 3.2.1 RT-Embed service and its official
Cosmos-Embed1 model generate compatible 768-dimensional embeddings for text,
an uploaded image, and an uploaded H.264 video.

The default command is inert. Acknowledged execution performs three local model
requests and temporarily uploads one 169 KB PNG plus one 2.6 MB, ten-second
video. It deletes both owned files and requires the complete file catalog, asset
statistics, model catalog, service identity, and operator-paused workloads to
match their pre-run state exactly.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 execute.py plan
PYTHONDONTWRITEBYTECODE=1 python3 execute.py execute \
  --ack I_ACK_TWO_OWNED_FILES_AND_THREE_LOCAL_RT_EMBED_INFERENCES
```
