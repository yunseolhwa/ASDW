from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from asdw_fusion.server import (
        BASELINE_FUSION_SENSORS,
        CANDIDATE_FUSION_SENSORS,
        AgentActRequest,
        AgentActionDecision,
        Detection,
        GroundingElementInput,
        GroundingReviewRequest,
        LLMCheckConfig,
        PredictRequest,
        decision_from_fused_scores,
        execute_agent_decision,
        fused_scores_from_votes,
        fusion_review_summary,
        gate_agent_decision,
        normalize_request_boxes,
    )
except ModuleNotFoundError as exc:
    missing = exc.name or "unknown"
    raise SystemExit(
        "verify_fusion_contracts.py imports WSL vision-server contracts. "
        "Run it with `.venv-wsl/bin/python scripts/verify_fusion_contracts.py`. "
        f"Missing module in this interpreter: {missing}"
    ) from exc


DEFAULT_OUTPUT_DIR = Path("artifacts/fusion-contract/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify local fusion contracts without calling input endpoints or loading models.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def run_case(name: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        details = fn() or {}
        return {
            "name": name,
            "status": "pass",
            "started_at": started.isoformat(),
            "details": details,
        }
    except AssertionError as exc:
        return {
            "name": name,
            "status": "fail",
            "started_at": started.isoformat(),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "error",
            "started_at": started.isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def expect_validation_error(fn: Callable[[], Any]) -> str:
    try:
        fn()
    except ValidationError as exc:
        return str(exc).splitlines()[0]
    raise AssertionError("expected Pydantic ValidationError")


def test_valid_press_sequence() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="captcha_prompt",
        action="press_sequence",
        keys=["a", "s", "d", "w"],
        confidence=0.91,
        reason="detected prompt",
    )
    assert decision.keys == ["A", "S", "D", "W"]
    return decision.model_dump()


def test_valid_type_text() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="typing_prompt",
        action="type_text",
        text="  hello  ",
        confidence=0.88,
        reason="typing field visible",
    )
    assert decision.text == "hello"
    return decision.model_dump()


def test_invalid_key_rejected() -> dict[str, Any]:
    error = expect_validation_error(
        lambda: AgentActionDecision(
            state="captcha_prompt",
            action="press_sequence",
            keys=["A", "X"],
            confidence=0.9,
            reason="bad key",
        )
    )
    return {"error": error}


def test_invalid_action_payload_rejected() -> dict[str, Any]:
    error = expect_validation_error(
        lambda: AgentActionDecision(
            state="idle",
            action="none",
            keys=["A"],
            confidence=0.9,
            reason="none should not have keys",
        )
    )
    return {"error": error}


def test_unknown_action_rejected() -> dict[str, Any]:
    error = expect_validation_error(
        lambda: AgentActionDecision.model_validate(
            {
                "state": "idle",
                "action": "click",
                "keys": [],
                "text": None,
                "confidence": 0.9,
                "reason": "unsupported action",
            }
        )
    )
    return {"error": error}


def test_low_confidence_blocks_action() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="captcha_prompt",
        action="press_sequence",
        keys=["A"],
        confidence=0.2,
        reason="uncertain",
    )
    gated, reason = gate_agent_decision(decision, {"detections": [{"key": "A"}]}, 0.6)
    assert gated.state == "blocked"
    assert gated.action == "none"
    assert reason and "below required" in reason
    return {"blocked_reason": reason, "gated": gated.model_dump()}


def test_blocked_state_blocks_action() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="blocked",
        action="press_sequence",
        keys=["A"],
        confidence=0.99,
        reason="state is blocked",
    )
    gated, reason = gate_agent_decision(decision, {"detections": [{"key": "A"}]}, 0.6)
    assert gated.state == "blocked"
    assert gated.action == "none"
    assert reason and "not allowed" in reason
    return {"blocked_reason": reason}


def test_empty_prediction_blocks_press_sequence() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="captcha_prompt",
        action="press_sequence",
        keys=["A"],
        confidence=0.95,
        reason="vision claimed prompt",
    )
    gated, reason = gate_agent_decision(decision, {"detections": []}, 0.6)
    assert gated.state == "blocked"
    assert gated.action == "none"
    assert reason and "no detections" in reason
    return {"blocked_reason": reason}


def test_observe_never_sends_input() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="captcha_prompt",
        action="press_sequence",
        keys=["A"],
        confidence=0.95,
        reason="valid action",
    )
    result = execute_agent_decision(decision, AgentActRequest(mode="observe"))
    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert "observe" in result["reason"]
    return result


def test_live_requires_explicit_allow() -> dict[str, Any]:
    decision = AgentActionDecision(
        state="captcha_prompt",
        action="press_sequence",
        keys=["A"],
        confidence=0.95,
        reason="valid action",
    )
    result = execute_agent_decision(decision, AgentActRequest(mode="live", allow_live_input=False))
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "allow_live_input" in result["reason"]
    return result


def test_predict_request_flat_boxes() -> dict[str, Any]:
    request = PredictRequest(
        image_b64="ZmFrZQ==",
        sensors=["template", "classifier"],
        boxes=[1, 2, 10, 20, 30, 40, 50, 60],
    )
    assert request.boxes == [(1, 2, 10, 20), (30, 40, 50, 60)]
    return {"boxes": [list(box) for box in request.boxes or []]}


def test_predict_request_bad_flat_boxes() -> dict[str, Any]:
    error = expect_validation_error(
        lambda: PredictRequest(
            image_b64="ZmFrZQ==",
            sensors=["template"],
            boxes=[1, 2, 3],
        )
    )
    return {"error": error}


def test_grounding_review_request_validates_element() -> dict[str, Any]:
    request = GroundingReviewRequest(
        image_b64="ZmFrZQ==",
        instruction="open the edit button",
        source="screenspot-pro",
        elements=[
            GroundingElementInput(
                id="sample-1",
                label="button",
                text="edit",
                category="Office",
                source="benchmark",
                confidence=0.77,
                box=(1, 2, 30, 40),
            )
        ],
    )
    assert request.elements[0].text == "edit"
    assert request.elements[0].box == (1, 2, 30, 40)
    return {
        "source": request.source,
        "instruction": request.instruction,
        "element": request.elements[0].model_dump(),
    }


def test_grounding_review_rejects_bad_confidence() -> dict[str, Any]:
    error = expect_validation_error(
        lambda: GroundingElementInput(
            label="button",
            confidence=1.5,
            box=(1, 2, 30, 40),
        )
    )
    return {"error": error}


def test_normalize_request_boxes_clamps_sorts_and_drops_invalid() -> dict[str, Any]:
    boxes = normalize_request_boxes(
        [
            (50, 10, 70, 30),
            (-10, -5, 15, 20),
            (80, 20, 70, 30),
            (20, 5, 30, 15),
        ],
        (60, 40),
    )
    assert boxes == [(0, 0, 15, 20), (20, 5, 30, 15), (50, 10, 60, 30)]
    return {"boxes": [list(box) for box in boxes]}


def test_classifier_weight_can_override_template_vote() -> dict[str, Any]:
    votes = {
        "template": {"A": 0.98, "S": 0.01, "D": 0.005, "W": 0.005},
        "classifier": {"A": 0.01, "S": 0.98, "D": 0.005, "W": 0.005},
    }
    fused = fused_scores_from_votes(votes)
    key, confidence = decision_from_fused_scores(fused)
    assert key == "S"
    assert confidence > 0.0
    return {"key": key, "confidence": round(confidence, 6), "fused": round_scores_for_report(fused)}


def test_fusion_review_summary_counts_agreement_and_rejection() -> dict[str, Any]:
    detections = [
        Detection(
            key="S",
            confidence=0.72,
            box=(0, 0, 10, 10),
            votes={
                "template": {"A": 0.9, "S": 0.1, "D": 0.0, "W": 0.0},
                "classifier": {"A": 0.1, "S": 0.9, "D": 0.0, "W": 0.0},
            },
            fused_scores={"A": 0.3, "S": 0.7, "D": 0.0, "W": 0.0},
        ),
        Detection(
            key="D",
            confidence=0.22,
            box=(12, 0, 22, 10),
            votes={
                "template": {"A": 0.0, "S": 0.0, "D": 0.8, "W": 0.2},
                "classifier": {"A": 0.0, "S": 0.0, "D": 0.75, "W": 0.25},
            },
            fused_scores={"A": 0.0, "S": 0.0, "D": 0.77, "W": 0.23},
        ),
    ]
    summary = fusion_review_summary(detections, ["template", "classifier"], 0.3)
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["sensor_sequences"] == {"template": "AD", "classifier": "SD"}
    assert len(summary["disagreements"]) == 2
    return summary


def test_baseline_and_candidate_sensors_are_separate() -> dict[str, Any]:
    baseline = set(BASELINE_FUSION_SENSORS)
    candidates = set(CANDIDATE_FUSION_SENSORS)
    assert baseline == {"template", "classifier"}
    assert candidates == {"clip", "trocr", "owlvit"}
    assert baseline.isdisjoint(candidates)
    return {"baseline": sorted(baseline), "candidates": sorted(candidates)}


def test_llm_check_timeout_is_shorter_than_generation_timeout() -> dict[str, Any]:
    config = LLMCheckConfig()
    assert 0.1 <= config.timeout_sec <= 30.0
    assert config.timeout_sec <= 2.5
    return {"timeout_sec": config.timeout_sec, "base_url": config.base_url, "model": config.model}


def round_scores_for_report(scores: dict[str, float]) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in sorted(scores.items())}


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Fusion Contract Verification",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Status: `{report['status']}`",
        f"- Passed: `{report['passed']}/{report['total']}`",
        "",
        "| Contract | Status | Notes |",
        "| --- | --- | --- |",
    ]
    for case in report["cases"]:
        notes = ""
        if case.get("error"):
            notes = case["error"].replace("|", "\\|")
        elif case.get("details"):
            notes = summarize_details(case["details"]).replace("|", "\\|")
        lines.append(f"| `{case['name']}` | `{case['status']}` | {notes} |")

    lines.extend(
        [
            "",
            "Scope:",
            "",
            "- This verifier imports local contract objects and pure helpers only.",
            "- It does not call `/keys/press`, `/text/type_keys`, `/agent/act`, or any daemon endpoint.",
            "- It does not load Hugging Face models or call SGLang.",
        ]
    )
    return "\n".join(lines) + "\n"


def summarize_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    if "blocked_reason" in details:
        return str(details["blocked_reason"])
    if "error" in details:
        return str(details["error"])
    if "boxes" in details:
        return f"boxes={details['boxes']}"
    if "key" in details:
        return f"key={details['key']} confidence={details.get('confidence')}"
    if "baseline" in details:
        return f"baseline={details['baseline']} candidates={details['candidates']}"
    if "status" in details and "reason" in details:
        return f"{details['status']}: {details['reason']}"
    return json.dumps(details, ensure_ascii=False, default=stringify)[:180]


def stringify(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(), ensure_ascii=False)
    if hasattr(value, "__dataclass_fields__"):
        return json.dumps(asdict(value), ensure_ascii=False)
    return str(value)


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = [
        ("valid_press_sequence", test_valid_press_sequence),
        ("valid_type_text", test_valid_type_text),
        ("invalid_key_rejected", test_invalid_key_rejected),
        ("invalid_action_payload_rejected", test_invalid_action_payload_rejected),
        ("unknown_action_rejected", test_unknown_action_rejected),
        ("low_confidence_blocks_action", test_low_confidence_blocks_action),
        ("blocked_state_blocks_action", test_blocked_state_blocks_action),
        ("empty_prediction_blocks_press_sequence", test_empty_prediction_blocks_press_sequence),
        ("observe_never_sends_input", test_observe_never_sends_input),
        ("live_requires_explicit_allow", test_live_requires_explicit_allow),
        ("predict_request_flat_boxes", test_predict_request_flat_boxes),
        ("predict_request_bad_flat_boxes", test_predict_request_bad_flat_boxes),
        ("grounding_review_request_validates_element", test_grounding_review_request_validates_element),
        ("grounding_review_rejects_bad_confidence", test_grounding_review_rejects_bad_confidence),
        ("normalize_request_boxes_clamps_sorts_and_drops_invalid", test_normalize_request_boxes_clamps_sorts_and_drops_invalid),
        ("classifier_weight_can_override_template_vote", test_classifier_weight_can_override_template_vote),
        ("fusion_review_summary_counts_agreement_and_rejection", test_fusion_review_summary_counts_agreement_and_rejection),
        ("baseline_and_candidate_sensors_are_separate", test_baseline_and_candidate_sensors_are_separate),
        ("llm_check_timeout_is_shorter_than_generation_timeout", test_llm_check_timeout_is_shorter_than_generation_timeout),
    ]

    results = [run_case(name, fn) for name, fn in cases]
    passed = sum(1 for item in results if item["status"] == "pass")
    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "status": "pass" if passed == len(results) else "fail",
        "passed": passed,
        "total": len(results),
        "cases": results,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=stringify), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{report['status']}: {passed}/{len(results)} contracts passed")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
