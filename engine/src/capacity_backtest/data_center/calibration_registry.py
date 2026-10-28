"""Review-gated calibration feedback with immutable version history and rollback."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path

from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class CalibrationCandidate:
    candidate_id: str
    model_name: str
    prior_version: str
    proposed_version: str
    evidence_cutoff: str
    training_fingerprint: str
    holdout_fingerprint: str
    prior_holdout_error: float
    proposed_holdout_error: float

    def validate(self) -> None:
        parse_aware_timestamp(self.evidence_cutoff, "calibration evidence cutoff")
        if not all((self.candidate_id, self.model_name, self.prior_version, self.proposed_version)):
            raise ValueError("calibration candidate identity is invalid")
        if not all(isfinite(v) for v in (self.prior_holdout_error, self.proposed_holdout_error)):
            raise ValueError("calibration errors must be finite")
        if self.prior_version == self.proposed_version or min(self.prior_holdout_error, self.proposed_holdout_error) < 0:
            raise ValueError("calibration versions or errors are invalid")
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in (self.training_fingerprint, self.holdout_fingerprint)):
            raise ValueError("calibration fingerprints must be SHA-256")


@dataclass(frozen=True)
class CalibrationDecision:
    candidate: CalibrationCandidate
    approved: bool
    reviewer_id: str
    decided_at: str
    reason: str


class CalibrationRegistry:
    def __init__(self, *, journal_path: Path | None = None) -> None:
        self._journal_path = journal_path
        self._decisions: dict[str, CalibrationDecision] = {}
        self._active: dict[str, str] = {}
        if journal_path is not None and journal_path.exists():
            for line in journal_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event["kind"] == "decision":
                    value = event["value"]
                    self.decide(CalibrationCandidate(**value["candidate"]), reviewer_id=value["reviewer_id"],
                                decided_at=value["decided_at"], approved=value["approved"], reason=value["reason"], _restore=True)
                elif event["kind"] == "rollback":
                    self.rollback(event["candidate_id"], _restore=True)
                else:
                    raise ValueError("unsupported calibration journal event")

    def _append(self, event: dict) -> None:
        if self._journal_path is not None:
            self._journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self._journal_path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
                target.flush()
                import os
                os.fsync(target.fileno())

    def decide(
        self, candidate: CalibrationCandidate, *, reviewer_id: str, decided_at: str,
        approved: bool, reason: str, _restore: bool = False,
    ) -> CalibrationDecision:
        candidate.validate()
        if parse_aware_timestamp(decided_at, "calibration decision time") < parse_aware_timestamp(candidate.evidence_cutoff, "evidence cutoff"):
            raise ValueError("decision precedes evidence cutoff")
        if approved and self._active.get(candidate.model_name, candidate.prior_version) != candidate.prior_version:
            raise ValueError("candidate does not extend the active calibration version")
        if candidate.candidate_id in self._decisions or not reviewer_id or not reason:
            raise ValueError("calibration decision is duplicate or incomplete")
        if approved and candidate.proposed_holdout_error >= candidate.prior_holdout_error:
            raise ValueError("calibration cannot be approved without held-out improvement")
        decision = CalibrationDecision(candidate, approved, reviewer_id, decided_at, reason)
        if not _restore:
            self._append({"kind": "decision", "value": asdict(decision)})
        self._decisions[candidate.candidate_id] = decision
        if approved:
            self._active[candidate.model_name] = candidate.proposed_version
        return decision

    def active_version(self, model_name: str) -> str | None:
        return self._active.get(model_name)

    def rollback(self, candidate_id: str, *, _restore: bool = False) -> str:
        decision = self._decisions.get(candidate_id)
        if decision is None or not decision.approved:
            raise ValueError("only an approved calibration can be rolled back")
        if self._active.get(decision.candidate.model_name) != decision.candidate.proposed_version:
            raise ValueError("only the active calibration can be rolled back")
        if not _restore:
            self._append({"kind": "rollback", "candidate_id": candidate_id})
        self._active[decision.candidate.model_name] = decision.candidate.prior_version
        return decision.candidate.prior_version
