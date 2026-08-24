#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, CTAILabs.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"
BASE_URL="http://127.0.0.1:31000/vst/api/v1"

usage() {
  echo "Usage: $0 {start|stop|status|list|logs}"
}

case "${1:-}" in
  start)
    docker compose -f "$COMPOSE_FILE" up -d
    for _ in $(seq 1 60); do
      if curl -fsS --max-time 3 "$BASE_URL/sensor/version" >/dev/null; then
        curl -fsS "$BASE_URL/sensor/version" | jq .
        exit 0
      fi
      sleep 1
    done
    docker logs --tail 100 vss-vios-nvstreamer >&2
    exit 1
    ;;
  stop)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  status)
    curl -fsS "$BASE_URL/sensor/version" | jq .
    docker ps --filter name=^/vss-vios-nvstreamer$ \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    ;;
  list)
    curl -fsS "$BASE_URL/sensor/streams" | jq .
    ;;
  logs)
    docker logs --tail 200 -f vss-vios-nvstreamer
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

