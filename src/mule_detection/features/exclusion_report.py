"""Historical audit counts and fitted exclusions have deliberately different scopes."""

from typing import Any

from mule_detection.domain.feature_policy import FeaturePolicy


def exclusion_report(
    policy: FeaturePolicy, dropped: dict[str, list[str]], selected: list[str], training_hash: str
) -> dict[str, Any]:
    return {
        "historical_registered_candidate_count": 2521,
        "historical_registered_exclusion_count": policy.historical_register_count,
        "historical_register_sha256": policy.historical_register_sha256,
        "feature_policy_version": policy.policy_version,
        "feature_policy_hash": policy.fingerprint,
        "fit_partition": "train",
        "training_fingerprint": training_hash,
        "fitted_selected_count": len(selected),
        "fitted_selected_features": selected,
        "fitted_exclusions": dropped,
        "missingness_comparison": "greater_than_or_equal",
        "missingness_threshold": policy.missingness_threshold,
    }
