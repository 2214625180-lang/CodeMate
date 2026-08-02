from collections.abc import Mapping
from typing import Any, Literal


VerificationStatus = Literal[
    "verified_success",
    "unverified_patch",
    "not_reproduced",
    "failed",
    "infra_error",
]
TestOutcome = Literal["passed", "failed", "skipped", "infra_error", "not_run"]

VERIFIED_SUCCESS: VerificationStatus = "verified_success"
UNVERIFIED_PATCH: VerificationStatus = "unverified_patch"
NOT_REPRODUCED: VerificationStatus = "not_reproduced"
FAILED: VerificationStatus = "failed"
INFRA_ERROR: VerificationStatus = "infra_error"

TERMINAL_AGENT_RUN_STATUSES = frozenset(
    {
        VERIFIED_SUCCESS,
        UNVERIFIED_PATCH,
        NOT_REPRODUCED,
        FAILED,
        INFRA_ERROR,
    }
)

_INFRASTRUCTURE_EXIT_CODES = frozenset({124, 125, 126, 127})


def classify_test_result(result: Mapping[str, Any] | None) -> TestOutcome:
    """Classify execution evidence without trusting a producer's `passed` flag alone."""
    if not result:
        return "not_run"

    failure_kind = result.get("failure_kind")
    if failure_kind == "infrastructure" or result.get("timed_out") is True:
        return "infra_error"
    if failure_kind == "skipped" or result.get("skipped_reason"):
        return "skipped"
    if failure_kind == "test_failure":
        return "failed"

    tests_ran = result.get("tests_ran") is True
    if not tests_ran:
        return "infra_error"

    exit_code = result.get("exit_code")
    if result.get("passed") is True and exit_code == 0:
        return "passed"
    if failure_kind == "infrastructure" or exit_code in _INFRASTRUCTURE_EXIT_CODES:
        return "infra_error"
    return "failed"


def route_after_reproduction(state: Mapping[str, Any]) -> str:
    baseline_outcome = classify_test_result(state.get("baseline_test_result"))
    if baseline_outcome in {"passed", "infra_error"}:
        return "final"
    return "continue"


def route_after_targeted_tests(state: Mapping[str, Any]) -> str:
    if not (state.get("apply_result") or {}).get("ok"):
        return _retry_or_finish(state)

    targeted_outcome = classify_test_result(state.get("targeted_test_result"))
    if targeted_outcome == "passed":
        return "regression"
    if targeted_outcome in {"skipped", "infra_error", "not_run"}:
        return "final"
    return _retry_or_finish(state)


def route_after_regression_checks(state: Mapping[str, Any]) -> str:
    regression_outcome = classify_test_result(state.get("regression_test_result"))
    if regression_outcome in {"passed", "skipped", "infra_error", "not_run"}:
        return "final"
    return _retry_or_finish(state)


def build_verification_result(state: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _mapping_or_none(state.get("baseline_test_result"))
    targeted = _mapping_or_none(state.get("targeted_test_result"))
    regression = _mapping_or_none(state.get("regression_test_result"))
    apply_result = _mapping_or_none(state.get("apply_result"))

    status, reason = _determine_status(
        baseline=baseline,
        targeted=targeted,
        regression=regression,
        apply_result=apply_result,
    )
    last_result = regression or targeted or baseline or {}
    targeted_passed = classify_test_result(targeted) == "passed"
    regression_passed = classify_test_result(regression) == "passed"

    return {
        "status": status,
        "reason": reason,
        "verified": status == VERIFIED_SUCCESS,
        # Compatibility fields remain strict: consumers cannot mistake a skipped run for a pass.
        "passed": status == VERIFIED_SUCCESS,
        "tests_ran": targeted_passed and regression_passed,
        "exit_code": last_result.get("exit_code"),
        "command": last_result.get("command"),
        "stdout": last_result.get("stdout", ""),
        "stderr": last_result.get("stderr", ""),
        "timed_out": bool(last_result.get("timed_out")),
        "runtime": last_result.get("runtime"),
        "skipped_reason": last_result.get("skipped_reason"),
        "baseline_reproduced": classify_test_result(baseline) == "failed",
        "patch_applied": bool(apply_result and apply_result.get("ok")),
        "targeted_tests_passed": targeted_passed,
        "regression_tests_passed": regression_passed,
        "baseline": baseline,
        "targeted": targeted,
        "regression": regression,
    }


def verification_evidence_is_complete(result: Mapping[str, Any] | None) -> bool:
    if not result or result.get("status") != VERIFIED_SUCCESS:
        return False
    return (
        classify_test_result(_mapping_or_none(result.get("baseline"))) == "failed"
        and classify_test_result(_mapping_or_none(result.get("targeted"))) == "passed"
        and classify_test_result(_mapping_or_none(result.get("regression"))) == "passed"
        and result.get("patch_applied") is True
    )


def verification_summary(status: VerificationStatus, reason: str) -> str:
    summaries = {
        VERIFIED_SUCCESS: "Patch 前已复现失败；Patch 后目标测试与回归测试均实际执行并通过。",
        UNVERIFIED_PATCH: "Patch 已应用，但目标测试或回归测试未实际运行，结果未验证。",
        NOT_REPRODUCED: "Patch 前测试已经通过，未复现原始失败，因此未生成修复。",
        FAILED: "Patch 应用或测试在最大迭代次数内未通过。",
        INFRA_ERROR: "沙箱、依赖、网络或执行基础设施故障，无法完成可信验证。",
    }
    return f"{summaries[status]} 原因：{reason}"


def _determine_status(
    *,
    baseline: Mapping[str, Any] | None,
    targeted: Mapping[str, Any] | None,
    regression: Mapping[str, Any] | None,
    apply_result: Mapping[str, Any] | None,
) -> tuple[VerificationStatus, str]:
    baseline_outcome = classify_test_result(baseline)
    if baseline_outcome == "infra_error":
        return INFRA_ERROR, "baseline_infrastructure_error"
    if baseline_outcome == "passed":
        return NOT_REPRODUCED, "baseline_already_passed"

    if not apply_result or not apply_result.get("ok"):
        return FAILED, "patch_not_applied"

    targeted_outcome = classify_test_result(targeted)
    if targeted_outcome == "infra_error":
        return INFRA_ERROR, "targeted_test_infrastructure_error"
    if targeted_outcome in {"skipped", "not_run"}:
        return UNVERIFIED_PATCH, "targeted_tests_not_run"
    if targeted_outcome == "failed":
        return FAILED, "targeted_tests_failed"

    regression_outcome = classify_test_result(regression)
    if regression_outcome == "infra_error":
        return INFRA_ERROR, "regression_test_infrastructure_error"
    if regression_outcome in {"skipped", "not_run"}:
        return UNVERIFIED_PATCH, "regression_tests_not_run"
    if regression_outcome == "failed":
        return FAILED, "regression_tests_failed"

    if baseline_outcome != "failed":
        return UNVERIFIED_PATCH, "baseline_failure_not_reproduced"
    return VERIFIED_SUCCESS, "baseline_failed_and_post_patch_suites_passed"


def _retry_or_finish(state: Mapping[str, Any]) -> str:
    if int(state.get("iterations", 0)) >= int(state.get("max_iterations", 3)):
        return "final"
    return "reflect"


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None
