"""Fail-closed shadow-pilot security, privacy, and recovery readiness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ShadowSecurityControls:
    read_only_accounts: bool
    network_segmented: bool
    tls_enforced: bool
    secrets_externalized: bool
    secrets_rotated: bool
    storage_encrypted: bool
    audit_logging: bool
    dependency_inventory: bool
    vulnerability_process: bool
    incident_response_tested: bool
    backup_restore_tested: bool
    adapter_allow_list: bool
    tenant_data_pseudonymized: bool


@dataclass(frozen=True)
class ShadowSecurityReadiness:
    ready: bool
    passed_controls: int
    total_controls: int
    blockers: tuple[str, ...]
    live_dispatch_authorized: bool = False


def assess_shadow_security(controls: ShadowSecurityControls) -> ShadowSecurityReadiness:
    values = controls.__dict__
    blockers = tuple(name for name, passed in values.items() if not passed)
    return ShadowSecurityReadiness(not blockers, sum(values.values()), len(values), blockers)


def pseudonymize_identifier(identifier: str, *, project_salt: str) -> str:
    if not identifier or len(project_salt) < 16:
        raise ValueError("pseudonymization requires an identifier and project-specific salt")
    return hashlib.sha256(f"{project_salt}:{identifier}".encode()).hexdigest()
