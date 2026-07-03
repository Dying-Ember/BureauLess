from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ProtocolError


@dataclass(frozen=True)
class AcceptancePolicy:
    policy_version: str
    review_required: bool
    allowed_review_actors: list[str]
    required_verification_statuses: list[str]
    allow_partial_acceptance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "review": {
                "required": self.review_required,
                "allowed_actors": self.allowed_review_actors,
            },
            "verification": {
                "required_statuses": self.required_verification_statuses,
            },
            "allow_partial_acceptance": self.allow_partial_acceptance,
        }


DEFAULT_ACCEPTANCE_POLICY = AcceptancePolicy(
    policy_version="acceptance-v1",
    review_required=True,
    allowed_review_actors=["orchestrator", "human"],
    required_verification_statuses=["passed"],
    allow_partial_acceptance=False,
)


def load_acceptance_policy(data: dict[str, Any]) -> AcceptancePolicy:
    review = _mapping(data, "review")
    verification = _mapping(data, "verification")
    actors = _string_list(review, "allowed_actors")
    invalid_actors = sorted(set(actors) - {"orchestrator", "human"})
    if invalid_actors:
        raise ProtocolError(
            "Acceptance policy allowed_review_actors contains invalid actors: "
            f"{', '.join(invalid_actors)}"
        )
    if _boolean(review, "required") and not actors:
        raise ProtocolError(
            "Acceptance policy requiring review must allow at least one review actor"
        )
    statuses = _string_list(verification, "required_statuses")
    if not statuses:
        raise ProtocolError(
            "Acceptance policy verification.required_statuses must not be empty"
        )
    return AcceptancePolicy(
        policy_version=_string(data, "policy_version"),
        review_required=_boolean(review, "required"),
        allowed_review_actors=actors,
        required_verification_statuses=statuses,
        allow_partial_acceptance=_boolean(data, "allow_partial_acceptance"),
    )


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ProtocolError(f"Acceptance policy field {key!r} must be an object")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(
            f"Acceptance policy field {key!r} must be a non-empty string"
        )
    return value


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ProtocolError(
            f"Acceptance policy field {key!r} must be a list of non-empty strings"
        )
    if len(value) != len(set(value)):
        raise ProtocolError(f"Acceptance policy field {key!r} must not repeat values")
    return value


def _boolean(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ProtocolError(f"Acceptance policy field {key!r} must be boolean")
    return value
