#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate and apply the offline Thor domain-pack contract."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PACK_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PACK_KEYS = {
    "schema_version",
    "id",
    "name",
    "description",
    "branding",
    "terminology",
    "demo_questions",
    "search_prompts",
    "verification_rules",
}
BRANDING_KEYS = {"title", "subtitle"}
TERMINOLOGY_KEYS = {"source", "event", "subject"}
RULE_KEYS = {
    "alert_type",
    "prompt",
    "system_prompt",
    "enrichment_prompt",
    "output_category",
    "vlm_params",
}
VLM_PARAM_KEYS = {"num_frames"}


class DomainPackError(RuntimeError):
    """A safe, operator-facing domain-pack error."""


def _require_text(value: Any, field: str, *, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise DomainPackError(f"{field} must be a string")
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        raise DomainPackError(f"{field} must contain {minimum}-{maximum} characters")
    if any(character in text for character in ("\n", "\r", "\x00")):
        raise DomainPackError(f"{field} must be a single line")
    return text


def _require_optional_text(value: Any, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _require_text(value, field, maximum=maximum)


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise DomainPackError(
            f"{field} contains unsupported keys: {', '.join(unknown)}"
        )


def validate_pack(raw: Any, path: Path) -> dict[str, Any]:
    """Return a normalized pack, or raise with a schema error."""
    if not isinstance(raw, dict):
        raise DomainPackError(f"{path.name}: root must be an object")
    _reject_unknown(raw, PACK_KEYS, path.name)
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise DomainPackError(f"{path.name}: schema_version must be {SCHEMA_VERSION}")
    pack_id = _require_text(raw.get("id"), "id", maximum=48)
    if not PACK_ID_PATTERN.fullmatch(pack_id):
        raise DomainPackError(
            "id must use lower-case letters, digits, and single hyphens"
        )
    if path.stem != pack_id:
        raise DomainPackError(f"{path.name}: id must match the filename")

    branding = raw.get("branding")
    if not isinstance(branding, dict):
        raise DomainPackError("branding must be an object")
    _reject_unknown(branding, BRANDING_KEYS, "branding")
    normalized_branding = {
        "title": _require_text(branding.get("title"), "branding.title", maximum=60),
        "subtitle": _require_text(
            branding.get("subtitle"), "branding.subtitle", maximum=80
        ),
    }

    terminology = raw.get("terminology")
    if not isinstance(terminology, dict) or set(terminology) != TERMINOLOGY_KEYS:
        raise DomainPackError("terminology must define source, event, and subject")
    normalized_terms = {
        key: _require_text(terminology[key], f"terminology.{key}", maximum=40)
        for key in sorted(TERMINOLOGY_KEYS)
    }

    def validate_prompts(field: str) -> list[str]:
        values = raw.get(field)
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise DomainPackError(f"{field} must contain 1-8 strings")
        normalized = [
            _require_text(value, f"{field}[{index}]", maximum=300, minimum=5)
            for index, value in enumerate(values)
        ]
        if len(set(normalized)) != len(normalized):
            raise DomainPackError(f"{field} contains duplicate entries")
        return normalized

    rules = raw.get("verification_rules")
    if not isinstance(rules, list) or len(rules) > 8:
        raise DomainPackError(
            "verification_rules must be a list with at most 8 entries"
        )
    normalized_rules: list[dict[str, Any]] = []
    seen_alert_types: set[str] = set()
    for index, rule in enumerate(rules):
        field = f"verification_rules[{index}]"
        if not isinstance(rule, dict):
            raise DomainPackError(f"{field} must be an object")
        _reject_unknown(rule, RULE_KEYS, field)
        alert_type = _require_text(
            rule.get("alert_type"), f"{field}.alert_type", maximum=200
        ).lower()
        if alert_type in seen_alert_types:
            raise DomainPackError(f"{field}.alert_type is duplicated")
        seen_alert_types.add(alert_type)
        vlm_params = rule.get("vlm_params")
        if not isinstance(vlm_params, dict):
            raise DomainPackError(f"{field}.vlm_params must be an object")
        _reject_unknown(vlm_params, VLM_PARAM_KEYS, f"{field}.vlm_params")
        frame_count = vlm_params.get("num_frames")
        if (
            isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or not 1 <= frame_count <= 4
        ):
            raise DomainPackError(
                f"{field}.vlm_params.num_frames must be an integer from 1 to 4"
            )
        normalized_rules.append(
            {
                "alert_type": alert_type,
                "prompt": _require_text(
                    rule.get("prompt"), f"{field}.prompt", maximum=5000
                ),
                "system_prompt": _require_optional_text(
                    rule.get("system_prompt"), f"{field}.system_prompt", maximum=5000
                ),
                "enrichment_prompt": _require_optional_text(
                    rule.get("enrichment_prompt"),
                    f"{field}.enrichment_prompt",
                    maximum=5000,
                ),
                "output_category": _require_optional_text(
                    rule.get("output_category"), f"{field}.output_category", maximum=200
                ),
                "vlm_params": {"num_frames": frame_count},
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "id": pack_id,
        "name": _require_text(raw.get("name"), "name", maximum=80),
        "description": _require_text(
            raw.get("description"), "description", maximum=300
        ),
        "branding": normalized_branding,
        "terminology": normalized_terms,
        "demo_questions": validate_prompts("demo_questions"),
        "search_prompts": validate_prompts("search_prompts"),
        "verification_rules": normalized_rules,
    }


def load_pack(pack_dir: Path, pack_id: str) -> dict[str, Any]:
    if not PACK_ID_PATTERN.fullmatch(pack_id):
        raise DomainPackError(f"invalid domain pack id: {pack_id}")
    path = pack_dir / f"{pack_id}.json"
    if not path.is_file():
        raise DomainPackError(f"unknown domain pack: {pack_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DomainPackError(f"cannot read {path.name}: {error}") from error
    return validate_pack(raw, path)


def load_all(pack_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(
        path for path in pack_dir.glob("*.json") if not path.name.startswith(".")
    )
    if not paths:
        raise DomainPackError(f"no domain packs found in {pack_dir}")
    return [load_pack(pack_dir, path.stem) for path in paths]


def render_pack(pack: dict[str, Any]) -> str:
    lines = [
        f"{pack['id']} - {pack['name']}",
        pack["description"],
        "",
        f"Branding: {pack['branding']['title']} / {pack['branding']['subtitle']}",
        "Terminology: "
        + ", ".join(f"{key}={value}" for key, value in pack["terminology"].items()),
        "",
        "Demo questions:",
    ]
    lines.extend(f"  - {prompt}" for prompt in pack["demo_questions"])
    lines.append("Search prompts:")
    lines.extend(f"  - {prompt}" for prompt in pack["search_prompts"])
    lines.append("Candidate-verification seeds:")
    if pack["verification_rules"]:
        lines.extend(
            f"  - {rule['alert_type']} -> {rule['output_category']} ({rule['vlm_params']['num_frames']} frames)"
            for rule in pack["verification_rules"]
        )
    else:
        lines.append("  - none")
    return "\n".join(lines)


def _canonical_rule(rule: dict[str, Any]) -> dict[str, Any]:
    vlm_params = (
        rule.get("vlm_params") if isinstance(rule.get("vlm_params"), dict) else {}
    )
    return {
        "alert_type": str(rule.get("alert_type", "")).strip().lower(),
        "prompt": rule.get("prompt"),
        "system_prompt": rule.get("system_prompt"),
        "enrichment_prompt": rule.get("enrichment_prompt"),
        "output_category": rule.get("output_category"),
        "vlm_params": {"num_frames": vlm_params.get("num_frames")},
    }


def _validate_local_api_url(api_url: str) -> str:
    parsed = urllib.parse.urlsplit(api_url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise DomainPackError(
            "alert bridge URL must be an unauthenticated local HTTP URL"
        )
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.lower() == "localhost"
    if not is_loopback:
        raise DomainPackError("domain apply refuses non-loopback alert bridge URLs")
    if parsed.query or parsed.fragment:
        raise DomainPackError("alert bridge URL must not contain a query or fragment")
    return urllib.parse.urlunsplit(parsed)


def _api_request(
    url: str, method: str = "GET", body: dict[str, Any] | None = None
) -> Any:
    payload = (
        None
        if body is None
        else json.dumps(body, separators=(",", ":")).encode("utf-8")
    )
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - loopback URL validated above
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(1000).decode("utf-8", errors="replace")
        raise DomainPackError(
            f"alert bridge rejected {method} {url} (HTTP {error.code}): {detail}"
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise DomainPackError(
            f"alert bridge is unavailable at {url}: {error}"
        ) from error


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "current_pack": None, "managed_rules": {}}
    if path.stat().st_uid != os.getuid() or (path.stat().st_mode & 0o777) != 0o600:
        raise DomainPackError(f"{path} must be owned by the current user and mode 0600")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DomainPackError(f"cannot read domain state: {error}") from error
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or not isinstance(state.get("managed_rules"), dict)
    ):
        raise DomainPackError("domain state has an unsupported schema")
    return state


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def apply_rules(
    pack: dict[str, Any], api_url: str, state_path: Path
) -> tuple[int, int, int]:
    """Idempotently apply owned rules, returning created/updated/adopted counts."""
    base_url = _validate_local_api_url(api_url)
    collection_url = f"{base_url}/verification/config"
    response = _api_request(collection_url)
    configs = response.get("configs") if isinstance(response, dict) else None
    if (
        not isinstance(response, dict)
        or response.get("status") != "success"
        or not isinstance(configs, list)
    ):
        raise DomainPackError(
            "alert bridge returned an invalid verification-config envelope"
        )
    current = {
        canonical["alert_type"]: canonical
        for item in configs
        if isinstance(item, dict) and (canonical := _canonical_rule(item))["alert_type"]
    }
    state = _load_state(state_path)
    managed = state["managed_rules"]
    created = updated = adopted = 0

    desired_types = {rule["alert_type"] for rule in pack["verification_rules"]}
    stale_types = sorted(set(managed) - desired_types)
    for alert_type in stale_types:
        entry = managed.get(alert_type)
        existing = current.get(alert_type)
        if not isinstance(entry, dict) or existing != entry.get("applied"):
            print(
                f"[WARN] Leaving modified former pack rule untouched: {alert_type}",
                file=sys.stderr,
            )
            managed.pop(alert_type, None)
            continue
        before = entry.get("before")
        detail_url = f"{collection_url}/{urllib.parse.quote(alert_type, safe='')}"
        if isinstance(before, dict):
            payload = {
                key: value for key, value in before.items() if key != "alert_type"
            }
            restored = _canonical_rule(_api_request(detail_url, "PUT", payload))
            current[alert_type] = restored
            print(f"[INFO] Restored pre-pack verification rule: {alert_type}")
        elif entry.get("created_by_pack") is True:
            _api_request(detail_url, "DELETE")
            current.pop(alert_type, None)
            print(f"[INFO] Removed pack-created verification rule: {alert_type}")
        else:
            print(f"[INFO] Preserved adopted verification rule: {alert_type}")
        managed.pop(alert_type, None)

    for desired in pack["verification_rules"]:
        alert_type = desired["alert_type"]
        existing = current.get(alert_type)
        entry = managed.get(alert_type)
        if existing == desired:
            if not isinstance(entry, dict):
                managed[alert_type] = {
                    "before": desired,
                    "applied": desired,
                    "created_by_pack": False,
                }
                adopted += 1
                print(f"[INFO] Adopted exact matching verification rule: {alert_type}")
            continue
        if existing is not None and (
            not isinstance(entry, dict) or existing != entry.get("applied")
        ):
            print(
                f"[WARN] Preserving operator-owned verification rule with conflicting alert_type: {alert_type}",
                file=sys.stderr,
            )
            continue
        payload = {key: value for key, value in desired.items() if key != "alert_type"}
        if existing is None:
            result = _api_request(collection_url, "POST", desired)
            applied = _canonical_rule(result)
            managed[alert_type] = {
                "before": None,
                "applied": applied,
                "created_by_pack": True,
            }
            current[alert_type] = applied
            created += 1
        else:
            detail_url = f"{collection_url}/{urllib.parse.quote(alert_type, safe='')}"
            result = _api_request(detail_url, "PUT", payload)
            applied = _canonical_rule(result)
            before = entry.get("before") if isinstance(entry, dict) else None
            created_by_pack = (
                entry.get("created_by_pack") is True
                if isinstance(entry, dict)
                else False
            )
            managed[alert_type] = {
                "before": before,
                "applied": applied,
                "created_by_pack": created_by_pack,
            }
            current[alert_type] = applied
            updated += 1

    state["current_pack"] = pack["id"]
    _write_private_json(state_path, state)
    return created, updated, adopted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack-dir", type=Path, default=Path(__file__).resolve().parent
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("list")
    show = subparsers.add_parser("show")
    show.add_argument("pack_id")
    get = subparsers.add_parser("get")
    get.add_argument("pack_id")
    get.add_argument("field", choices=("title", "subtitle", "name"))
    apply_parser = subparsers.add_parser("apply-rules")
    apply_parser.add_argument("pack_id")
    apply_parser.add_argument("--api-url", required=True)
    apply_parser.add_argument("--state", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "validate":
            packs = load_all(args.pack_dir)
            print(
                f"[OK] Validated {len(packs)} domain packs (schema v{SCHEMA_VERSION})."
            )
        elif args.command == "list":
            for pack in load_all(args.pack_dir):
                print(f"{pack['id']}\t{pack['name']}\t{pack['description']}")
        elif args.command == "show":
            print(render_pack(load_pack(args.pack_dir, args.pack_id)))
        elif args.command == "get":
            pack = load_pack(args.pack_dir, args.pack_id)
            if args.field == "name":
                print(pack["name"])
            else:
                print(pack["branding"][args.field])
        elif args.command == "apply-rules":
            pack = load_pack(args.pack_dir, args.pack_id)
            created, updated, adopted = apply_rules(pack, args.api_url, args.state)
            print(
                "[OK] Candidate-verification seeds synchronized "
                f"({created} created, {updated} updated, {adopted} adopted)."
            )
        else:  # pragma: no cover - argparse enforces this
            raise DomainPackError(f"unsupported command: {args.command}")
    except DomainPackError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
