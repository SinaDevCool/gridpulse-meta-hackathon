"""Authoritative transport shell; nested physical validation remains in domain contracts."""

FACILITY_PLAN_REQUIRED = frozenset(
    {
        "schema_version",
        "portfolio_id",
        "requirement",
        "intervals",
        "facility",
        "workloads",
        "profiles",
        "policy",
        "economics",
        "cooling",
    }
)
FACILITY_PLAN_OPTIONAL = frozenset(
    {
        "batteries",
        "onsite_generation_mw",
        "fatigue_limits",
        "fleet_gpu_capacity",
        "idle_gpu_power_watts",
        "planning_context",
    }
)


def facility_plan_transport_schema() -> dict[str, object]:
    record = {"type": "object", "additionalProperties": True}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(FACILITY_PLAN_REQUIRED),
        "properties": {
            "schema_version": {"const": "gridpulse-facility-plan-request-v1"},
            "portfolio_id": {"type": "string", "minLength": 1, "maxLength": 200},
            **{
                name: record
                for name in ("requirement", "facility", "policy", "economics", "cooling")
            },
            "intervals": {"type": "array", "minItems": 1, "maxItems": 35040, "items": record},
            **{
                name: {"type": "array", "minItems": 1, "maxItems": 5000, "items": record}
                for name in ("workloads", "profiles")
            },
            "batteries": {"type": "array", "maxItems": 100, "items": record},
            "onsite_generation_mw": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": 35040,
                "items": {"type": "number", "minimum": 0},
            },
            "fatigue_limits": {"type": ["object", "null"]},
            "fleet_gpu_capacity": {"type": ["integer", "null"], "minimum": 1},
            "idle_gpu_power_watts": {"type": "number", "minimum": 0},
            "planning_context": {"type": ["object", "null"]},
        },
    }
