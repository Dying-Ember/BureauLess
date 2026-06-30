from __future__ import annotations

from pathlib import Path

import yaml

from ..errors import ProtocolError


def load_yaml_event(path: Path) -> dict:
    return load_yaml_mapping(path, "Ledger event")


def load_yaml_mapping(path: Path, label: str) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProtocolError(f"{label} document must be an object")
    return data
