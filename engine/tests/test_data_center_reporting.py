import hashlib
import json

from capacity_backtest.data_center.reporting import build_data_center_enquiry_package

from .test_data_center_flexibility_assessment import requirement


def test_evidence_package_is_hashed_deterministic_and_nonclaiming(tmp_path) -> None:
    first = build_data_center_enquiry_package(tmp_path / "one", package_id="pkg", artifacts={"requirement": requirement()})
    second = build_data_center_enquiry_package(tmp_path / "two", package_id="pkg", artifacts={"requirement": requirement()})
    assert first.package_fingerprint == second.package_fingerprint
    manifest = json.loads(first.manifest_path.read_text())
    assert manifest["artifact_sha256"]["operator-enquiry.json"] == hashlib.sha256(first.json_path.read_bytes()).hexdigest()
    assert not manifest["capacity_claim"] and not first.automatic_live_dispatch_authorized
