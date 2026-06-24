from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..core import ProtocolError


@dataclass(frozen=True)
class CostEstimate:
    cost_usd: float | None
    source: str
    confidence: str
    pricing_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_usd": self.cost_usd,
            "source": self.source,
            "confidence": self.confidence,
            "pricing_model": self.pricing_model,
        }


def load_price_snapshot(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError("Price snapshot document must be an object")
    if "models" not in data or not isinstance(data["models"], dict):
        raise ProtocolError("Price snapshot must contain a models mapping")
    return data


def estimate_cost_from_snapshot(
    snapshot: dict[str, Any],
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> CostEstimate:
    model_data = snapshot["models"].get(model)
    if not isinstance(model_data, dict):
        return CostEstimate(
            cost_usd=None,
            source="price_snapshot_missing_model",
            confidence="none",
            pricing_model="unknown",
        )

    pricing_model = _string_or_unknown(model_data.get("pricing_model"))
    source = _string_or_unknown(model_data.get("source"), snapshot.get("source", "unknown"))
    confidence = _string_or_unknown(model_data.get("confidence"), "unknown")

    if pricing_model != "token":
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence=confidence,
            pricing_model=pricing_model,
        )

    if input_tokens is None or output_tokens is None:
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence="none",
            pricing_model=pricing_model,
        )

    input_per_million = _float_or_none(model_data.get("input_per_million"))
    output_per_million = _float_or_none(model_data.get("output_per_million"))
    if input_per_million is None or output_per_million is None:
        return CostEstimate(
            cost_usd=None,
            source=source,
            confidence="none",
            pricing_model=pricing_model,
        )

    cost_usd = (input_tokens / 1_000_000) * input_per_million + (
        output_tokens / 1_000_000
    ) * output_per_million
    return CostEstimate(
        cost_usd=round(cost_usd, 6),
        source=source,
        confidence=confidence,
        pricing_model=pricing_model,
    )


def _string_or_unknown(value: Any, default: str = "unknown") -> str:
    return value if isinstance(value, str) and value else default


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
