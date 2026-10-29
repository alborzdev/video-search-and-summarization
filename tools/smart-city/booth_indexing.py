#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Control per-source booth indexing, preserving CV, footage and existing vectors."""

from __future__ import annotations

import argparse
import json
from urllib.parse import quote
from urllib.request import Request, urlopen


def request(
    origin: str, path: str, method: str = "GET", payload: dict | None = None
) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    call = Request(
        origin.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(call, timeout=100) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origin", default="http://127.0.0.1:8100", help="Existing Agent HTTP origin"
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument(
        "--name", help="Exact registered source name; required for mutations/search"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    policy = sub.add_parser("policy")
    policy.add_argument("mode", choices=("on-demand", "disabled", "continuous"))
    start = sub.add_parser("start")
    start.add_argument(
        "--seconds", type=int, default=120, choices=range(30, 601), metavar="30..600"
    )
    sub.add_parser("cancel")
    for action in ("search-request", "search"):
        search = sub.add_parser(action)
        search.add_argument("query")
        search.add_argument(
            "--session-id",
            help="Explicit selected session; defaults to the current finite session",
        )
        search.add_argument(
            "--top-k", type=int, default=6, choices=range(1, 21), metavar="1..20"
        )
    args = parser.parse_args()
    path = f"/api/v1/rtsp-streams/{quote(args.source_id, safe='')}/indexing"
    if args.command == "status":
        result = request(args.origin, path)
    else:
        if not args.name:
            parser.error("--name is required for this command")
        if args.command == "policy":
            result = request(
                args.origin, path, "PUT", {"name": args.name, "mode": args.mode}
            )
        elif args.command in {"start", "cancel"}:
            body = {"name": args.name, "action": args.command}
            if args.command == "start":
                body["durationSeconds"] = args.seconds
            result = request(args.origin, path, "POST", body)
        else:
            session_id = args.session_id
            if not session_id:
                status = request(args.origin, path)
                session_id = (status.get("session") or {}).get("id")
            if not session_id:
                parser.error(
                    "No current finite session exists; start an indexing window first"
                )
            prepared = request(
                args.origin,
                path + "/search-request",
                "POST",
                {
                    "name": args.name,
                    "sessionId": session_id,
                    "query": args.query,
                    "topK": args.top_k,
                },
            )
            if args.command == "search-request":
                result = prepared
            else:
                # The destination is fixed locally; never follow a supplied URL.
                found = request(
                    args.origin, "/api/v1/embed_search", "POST", prepared["request"]
                )
                result = {
                    "sessionId": session_id,
                    "scope": {**prepared["scope"], "executed": True},
                    "results": found.get("results", []),
                }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
