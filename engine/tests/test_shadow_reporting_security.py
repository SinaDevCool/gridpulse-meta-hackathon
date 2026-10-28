from capacity_backtest.data_center.security_readiness import (
    ShadowSecurityControls,
    assess_shadow_security,
    pseudonymize_identifier,
)
from capacity_backtest.data_center.shadow_monitor import assess_shadow_divergence
from capacity_backtest.data_center.shadow_reporting import build_shadow_operations_snapshot
from capacity_backtest.data_center.telemetry_quality import TelemetryQualityAssessment


def test_shadow_snapshot_and_security_are_fail_closed() -> None:
    telemetry = TelemetryQualityAssessment(True, 0, 0, 0, 0, 0, ())
    divergence = assess_shadow_divergence((1,), (1,), uncertainty_band_mw=(0.1,), evaluated_at="2026-01-01T00:00:00+00:00")
    snapshot = build_shadow_operations_snapshot("f", "2026-01-01T00:00:00+00:00", "a" * 64, telemetry, divergence, required_reduction_mw=1, delivered_reduction_mw=1)
    assert not snapshot.unresolved_blockers and not snapshot.automatic_live_dispatch_authorized
    controls = ShadowSecurityControls(*([True] * 12), tenant_data_pseudonymized=False)
    readiness = assess_shadow_security(controls)
    assert not readiness.ready and readiness.blockers == ("tenant_data_pseudonymized",)
    assert pseudonymize_identifier("tenant", project_salt="project-specific-salt") != "tenant"
