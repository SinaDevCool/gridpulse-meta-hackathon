"""Serialization and validation helpers shared by domain contracts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any, cast


def require_non_empty(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} is required")


def parse_aware_timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


class DomainContract:
    schema_version: str

    def validate(self) -> None:
        raise NotImplementedError

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        # Concrete domain contracts are frozen dataclasses; the abstract base cannot
        # express that structural constraint to the dataclasses typing stubs.
        return json_value(asdict(cast(Any, self)))
