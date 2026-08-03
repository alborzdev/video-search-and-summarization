from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any


PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4]
EXPECTED_CAPABILITIES = [
    "evaluation.agent.report",
    "evaluation.agent.qa",
    "evaluation.agent.trajectory",
    "evaluation.agent.multi-turn",
    "evaluation.agent.execution-artifacts",
]


class EvidenceError(RuntimeError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=_no_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_repo_path(relative: str) -> Path:
    path = (REPO_ROOT / relative).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise EvidenceError(f"lock escapes repository: {relative}") from exc
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"lock is not a regular file: {relative}")
    return path


def verify_locks(contract: dict[str, Any]) -> None:
    if contract.get("capability_ids") != EXPECTED_CAPABILITIES:
        raise EvidenceError("capability list is not exact")
    if contract.get("proof_ceiling") != "nonpromotable_mechanics_only":
        raise EvidenceError("proof ceiling changed")
    policy = contract.get("policy", {})
    required_false = (
        "network_allowed",
        "downloads_allowed",
        "services_allowed",
        "models_allowed",
        "install_proprietary_codecs",
        "canonical_metadata_mutation_allowed",
        "semantic_judge_execution_authorized",
        "product_nat_eval_execution_authorized",
    )
    if any(policy.get(key) is not False for key in required_false):
        raise EvidenceError("offline/non-execution policy changed")
    if policy.get("warehouse_sample_bundle") != "excluded":
        raise EvidenceError("warehouse sample must remain excluded")

    for row in contract["source_locks"] + contract["config_locks"]:
        actual = sha_file(_safe_repo_path(row["path"]))
        if actual != row["sha256"]:
            raise EvidenceError(f"source/config lock mismatch: {row['path']}")
    nat = contract["nat_lock"]
    for path_key, sha_key in (
        ("pyproject_path", "pyproject_sha256"),
        ("uv_lock_path", "uv_lock_sha256"),
    ):
        if sha_file(_safe_repo_path(nat[path_key])) != nat[sha_key]:
            raise EvidenceError(f"NAT lock mismatch: {nat[path_key]}")
    pyproject = _safe_repo_path(nat["pyproject_path"]).read_text()
    if (
        "nvidia-nat[async-endpoints,langchain,mcp,opentelemetry,phoenix,profiler,s3]==1.6.0"
        not in pyproject
    ):
        raise EvidenceError("exact NAT 1.6.0 dependency is absent")
    judge_profile = nat["report_judge_profile"]
    if judge_profile != {
        "upstream_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
        "upstream_config_raw_sha256": "e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79",
        "local_thor_config_sha256": "5d07f34fc24921326ca803c7d2958a7c6ac6428c834d628db259b417a56df5a9",
        "evaluator_metric": "llm_judge",
        "llm_name": "eval_llm_judge",
        "llm_profile": "eval_llm_judge",
        "max_tokens": 4096,
        "temperature": 0.0,
        "local_lock_reason": "Thor locks the checked working profile; upstream raw SHA records repository authority for the same judge selection/profile semantics.",
    }:
        raise EvidenceError("report judge profile authority changed")
    fixture_lock = contract["fixture_spec"]
    if sha_file(_safe_repo_path(fixture_lock["path"])) != fixture_lock["sha256"]:
        raise EvidenceError("fixture specification lock mismatch")


def verify_product_contract_tokens() -> None:
    token_sets = {
        "services/agent/src/vss_agents/evaluators/report_evaluator/register.py": [
            "eval_metrics_config_path",
            "METRIC_REGISTRY",
            "include_vlm_output",
            "evaluation_method_id",
        ],
        "services/agent/src/vss_agents/evaluators/customized_qa_evaluator/register.py": [
            "question",
            "answer",
            "reference",
            "llm_judge_reasoning",
        ],
        "services/agent/src/vss_agents/evaluators/customized_trajectory_evaluator/register.py": [
            "custom_prompt_template_with_reference",
            "custom_prompt_template_without_reference",
            "tool_schemas",
            "conversation_history",
            "track_agent_selected_tools_only",
        ],
        "services/agent/src/vss_agents/evaluators/evaluate_patch.py": [
            "_conversation_history",
            "_all_turn_tool_results",
        ],
        "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml": [
            "customized_qa_evaluator",
            "customized_trajectory_evaluator",
            "report_evaluator",
            "evaluation_method_id: qa",
            "evaluation_method_id: trajectory",
            "evaluation_method_id: report",
        ],
        "deploy/docker/developer-profiles/dev-profile-base/eval/README_eval.md": [
            "docker exec vss-agent nat eval",
            "workflow_output.json",
            "report_evaluator_output.json",
            "qa_evaluator_output.json",
            "trajectory_evaluator_output.json",
        ],
    }
    for relative, tokens in token_sets.items():
        text = _safe_repo_path(relative).read_text()
        missing = [token for token in tokens if token not in text]
        if missing:
            raise EvidenceError(
                f"product contract tokens missing from {relative}: {missing}"
            )
    profile = _safe_repo_path(
        "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml"
    ).read_text()
    judge_match = re.search(
        r"(?ms)^  eval_llm_judge:\n.*?^    max_tokens: 4096\n^    temperature: 0\.0\n",
        profile,
    )
    report_match = re.search(
        r"(?ms)^    report_evaluator:\n.*?^      metric_configs:\n"
        r"^        llm_judge:\n^          llm_name: eval_llm_judge\n",
        profile,
    )
    if judge_match is None or report_match is None:
        raise EvidenceError(
            "exact report evaluator to eval_llm_judge profile binding is absent"
        )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EvidenceError(f"refusing symlink output: {path}")
    path.write_bytes(canonical_bytes(value))


def materialize(root: Path, spec: dict[str, Any]) -> dict[str, str]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise EvidenceError("fixture root cannot be a symlink")
    _write_json(root / "reports/reference.json", spec["report"]["reference"])
    _write_json(root / "reports/actual.json", spec["report"]["actual"])
    _write_json(
        root / "reports/adjacent-negative.json", spec["report"]["adjacent_negative"]
    )
    dataset = {
        "qa": spec["qa"],
        "qa_adjacent_negatives": spec["qa_adjacent_negatives"],
        "trajectory": spec["trajectory"],
        "multi_turn": spec["multi_turn"],
    }
    _write_json(root / "dataset.json", dataset)
    config_text = (
        "# Generated mechanics-only configuration; do not execute as semantic evidence.\n"
        "eval:\n  general:\n    output_dir: generated/results\n"
        "    dataset:\n      _type: json\n      file_path: generated/dataset.json\n"
        "  evaluators:\n    qa_evaluator:\n      _type: customized_qa_evaluator\n"
        "      evaluation_method_id: qa\n    trajectory_evaluator:\n"
        "      _type: customized_trajectory_evaluator\n      evaluation_method_id: trajectory\n"
        "    report_evaluator:\n      _type: report_evaluator\n      evaluation_method_id: report\n"
    )
    (root / "nat-config-mechanics.yml").write_text(config_text)
    for name in spec["execution"]["artifacts"]:
        _write_json(root / "results" / name, {"synthetic_mechanics_placeholder": name})
    return {
        str(path.relative_to(root)): sha_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _f1(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    precision = overlap / len(a)
    recall = overlap / len(b)
    return (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )


def check_report(spec: dict[str, Any]) -> bool:
    report = spec["report"]
    reference, actual, negative = (
        report["reference"],
        report["actual"],
        report["adjacent_negative"],
    )
    positive = (
        actual["title"] == reference["title"]
        and bool(actual["identifier"].strip())
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", actual["date"]) is not None
        and _f1(actual["tags"], reference["tags"]) == 1.0
        and actual["dynamic_zone"] == reference["dynamic_zone"]
        and actual["analysis"] != reference["analysis"]
        and report["judge_profile_config"]
        == {
            "evaluator_metric": "llm_judge",
            "llm_name": "eval_llm_judge",
            "llm_profile": "eval_llm_judge",
            "max_tokens": 4096,
            "temperature": 0.0,
        }
        and report["deterministic_metrics"]
        == ["exact_match", "f1", "regex", "non_empty"]
        and report["judge_metric"] == "llm_judge"
    )
    negative_rejected = (
        negative["title"] != reference["title"]
        and not negative["identifier"]
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", negative["date"]) is None
        and _f1(negative["tags"], reference["tags"]) < 1.0
    )
    return positive and negative_rejected


def check_qa(spec: dict[str, Any]) -> bool:
    rows = {row["id"]: row for row in spec["qa"]}
    required = {"qa-exact", "qa-incomplete", "qa-semantic"}
    if set(rows) != required or any(
        row["evaluation_method"] != ["qa"] for row in rows.values()
    ):
        return False
    exact = rows["qa-exact"]["generated_answer"] == rows["qa-exact"]["ground_truth"]
    incomplete = (
        "north loading bay" not in rows["qa-incomplete"]["generated_answer"].lower()
    )
    semantic_needs_judge = (
        rows["qa-semantic"]["generated_answer"] != rows["qa-semantic"]["ground_truth"]
    )
    negatives = {row["id"]: row for row in spec["qa_adjacent_negatives"]}
    missing_gt_rejected = "ground_truth" not in negatives["qa-missing-ground-truth"]
    wrong_method_rejected = negatives["qa-wrong-method"]["evaluation_method"] != ["qa"]
    return (
        exact
        and incomplete
        and semantic_needs_judge
        and missing_gt_rejected
        and wrong_method_rejected
    )


def _valid_tool_rows(rows: Any) -> bool:
    return (
        isinstance(rows, list)
        and bool(rows)
        and all(
            isinstance(row, dict)
            and isinstance(row.get("step"), int)
            and isinstance(row.get("name"), str)
            and isinstance(row.get("params"), dict)
            for row in rows
        )
    )


def check_trajectory(spec: dict[str, Any]) -> bool:
    group = spec["trajectory"]
    with_ref = group["with_reference"]
    without_ref = group["without_reference"]
    malformed = group["adjacent_negative"]
    bad_ref = group["malformed_reference"]["trajectory_ground_truth"][0]["params"][
        "sensor_id"
    ]["$ref"]
    steps = [row["step"] for row in with_ref["trajectory_ground_truth"]]
    return (
        _valid_tool_rows(with_ref["trajectory_ground_truth"])
        and steps == [1, 1, 2]
        and "trajectory_ground_truth" not in without_ref
        and bool(without_ref["conversation"])
        and bool(without_ref["tool_schemas"])
        and not _valid_tool_rows(malformed["trajectory_ground_truth"])
        and "tool" not in bad_ref
        and group["track_agent_selected_tools_only"] is True
    )


def check_multi_turn(spec: dict[str, Any]) -> bool:
    group = spec["multi_turn"]
    turns = group["turns"]
    expected_ids = [f"{group['id']}_{turn['id']}" for turn in turns]
    positive = (
        len(turns) == 2
        and [turn["id"] for turn in turns] == ["turn-1", "turn-2"]
        and group["result_ids"] == expected_ids
        and group["parallel_conversation_ids"] == ["conversation-1", "conversation-2"]
        and turns[1]["conversation"][0]["content"] == turns[0]["query"]
    )
    adjacent_negative = dict(group)
    adjacent_negative["turns"] = list(reversed(turns))
    negative_rejected = [turn["id"] for turn in adjacent_negative["turns"]] != [
        "turn-1",
        "turn-2",
    ]
    return positive and negative_rejected


def check_artifacts(root: Path, expected: list[str]) -> bool:
    results = root / "results"
    actual = sorted(path.name for path in results.iterdir() if path.is_file())
    if actual != sorted(expected):
        return False
    removed = results / expected[-1]
    payload = removed.read_bytes()
    removed.unlink()
    negative_rejected = sorted(
        path.name for path in results.iterdir() if path.is_file()
    ) != sorted(expected)
    removed.write_bytes(payload)
    return negative_rejected and sorted(
        path.name for path in results.iterdir() if path.is_file()
    ) == sorted(expected)


def check_execution_contract(spec: dict[str, Any], root: Path) -> bool:
    execution = spec["execution"]
    valid = {
        "all",
        "qa",
        "trajectory",
        "report",
        "qa,trajectory",
        "qa,report",
        "trajectory,report",
        "qa,trajectory,report",
    }
    invalid = {"all,qa", "qa,all", "unknown", ""}
    return (
        set(execution["valid_filters"]) == valid
        and set(execution["invalid_filters"]) == invalid
        and execution["positive_precondition"] == {"referenced_videos_uploaded": True}
        and execution["adjacent_negative_precondition"]
        == {"referenced_videos_uploaded": False}
        and check_artifacts(root, execution["artifacts"])
    )


def _capability_results(executed: bool) -> list[dict[str, Any]]:
    scopes = {
        "evaluation.agent.report": [
            "deterministic metric fixture mechanics",
            "dynamic field fixture",
            "llm_judge deliberately not scored",
        ],
        "evaluation.agent.qa": [
            "exact/incomplete/paraphrase fixture routing",
            "no semantic score produced",
        ],
        "evaluation.agent.trajectory": [
            "reference/no-reference schema mechanics",
            "parallel-step and judge quality not scored",
        ],
        "evaluation.agent.multi-turn": [
            "two-turn order/context/result-id mechanics",
            "workflow conversation execution not run",
        ],
        "evaluation.agent.execution-artifacts": [
            "exact filename-set mechanics",
            "files are synthetic placeholders, not NAT outputs",
        ],
    }
    results = []
    for capability_id in EXPECTED_CAPABILITIES:
        judge = capability_id != "evaluation.agent.execution-artifacts"
        results.append(
            {
                "capability_id": capability_id,
                "mechanics_status": "passed_local_stub" if executed else "planned",
                "semantic_status": (
                    "blocked_no_authorized_local_judge_service"
                    if judge
                    else "blocked_product_nat_eval_not_executed"
                ),
                "advertised_semantics_proven": False,
                "adjacent_negative_passed": executed,
                "proof_scope": scopes[capability_id],
                "promotable": False,
            }
        )
    return results


def build_result(
    contract: dict[str, Any], *, executed: bool, hashes: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "executed-nonpromotable-mechanics"
        if executed
        else "plan-nonpromotable",
        "source_revision": contract["source_revision"],
        "locks": {
            "verified": executed,
            "source_count": len(contract["source_locks"]),
            "config_count": len(contract["config_locks"]),
            "nat_version": contract["nat_lock"]["version"],
            "image_digest": contract["nat_lock"]["image_digest"],
        },
        "fixture_run": {
            "materialized": executed,
            "generated_file_hashes": hashes or {},
            "deterministic": executed,
            "adjacent_negatives_passed": executed,
            "cleanup_passed": executed,
        },
        "nat_observation": {
            "cached_image_inspected": True,
            "cli_help_observed": True,
            "component_registration_observed": True,
            "config_file_execution": "not_executed_no_product_or_service_authorization",
            "semantic_judge_execution": "blocked_no_authorized_local_judge_service",
        },
        "capability_results": _capability_results(executed),
        "confinement": {
            "network_calls": 0,
            "downloads": 0,
            "service_lifecycle_calls": 0,
            "model_accesses": 0,
            "docker_calls": 0,
            "product_subprocess_calls": 0,
            "warehouse_sample_accesses": 0,
            "install_proprietary_codecs": False,
        },
        "promotion": {
            "ledger_mutation_performed": False,
            "oracle_mutation_performed": False,
            "selector_mutation_performed": False,
            "eligible_capability_ids": [],
            "receipt_is_runtime_evidence": False,
            "aggregate_is_promotable": False,
            "requires_authorized_local_judge_and_product_run": True,
        },
    }


def execute(contract: dict[str, Any]) -> dict[str, Any]:
    verify_locks(contract)
    verify_product_contract_tokens()
    spec = strict_json(_safe_repo_path(contract["fixture_spec"]["path"]))
    with tempfile.TemporaryDirectory(prefix="vss-agent-eval-a-") as first_name:
        with tempfile.TemporaryDirectory(prefix="vss-agent-eval-b-") as second_name:
            first, second = Path(first_name), Path(second_name)
            first_hashes = materialize(first, spec)
            second_hashes = materialize(second, spec)
            if first_hashes != second_hashes:
                raise EvidenceError("generated fixtures are not deterministic")
            checks = {
                "report": check_report(spec),
                "qa": check_qa(spec),
                "trajectory": check_trajectory(spec),
                "multi_turn": check_multi_turn(spec),
                "artifacts": check_execution_contract(spec, first),
            }
            if not all(checks.values()):
                raise EvidenceError(f"mechanics/negative check failed: {checks}")
    if Path(first_name).exists() or Path(second_name).exists():
        raise EvidenceError("temporary fixture cleanup failed")
    return build_result(contract, executed=True, hashes=first_hashes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nonpromoting Agent Evaluation mechanics producer"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run offline deterministic stub/mechanics checks",
    )
    parser.add_argument(
        "--output", type=Path, help="optional new receipt path outside the repository"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = strict_json(PACKAGE / "contract.json")
    result = (
        execute(contract) if args.execute else build_result(contract, executed=False)
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        if output.exists():
            raise EvidenceError(f"refusing to overwrite output: {output}")
        try:
            output.relative_to(REPO_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise EvidenceError("receipt output must be outside the repository")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
