# Shared Logstash offline pack

The reviewed 4.8 MiB protobuf plugin pack and its checksum are checked in so a
fresh clone can build the demo without depending on byte-identical ZIP generation
from a later RubyGems resolution. The expected checksum lock remains authoritative.
Spark verifies this bundled archive before building; it does not regenerate it.
The runtime derivative installs it with build networking disabled.

To deliberately regenerate and review the dependency pack while connected:

```sh
deploy/docker/services/infra/elk/logstash/stage-protobuf-offline-pack.sh
```

Both staging and runtime builds fail on digest drift. Do not silently update the
expected checksum to make an unexpected download pass. Non-demo profiles retain
NVIDIA's upstream Logstash behavior.
