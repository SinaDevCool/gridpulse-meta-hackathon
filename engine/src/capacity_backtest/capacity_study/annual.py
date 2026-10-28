"""Idempotent, resumable work ledger for annual capacity studies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from capacity_backtest.storage import atomic_write


def plan_annual_chunks(
    chronology_rows: Path,
    destination: Path,
    *,
    hours_per_chunk: int = 168,
) -> Path:
    """Create a compact deterministic annual execution plan instead of 8,760 cloud files."""
    if hours_per_chunk <= 0:
        raise ValueError("hours_per_chunk must be positive")
    rows = [json.loads(line) for line in chronology_rows.read_text(encoding="utf-8").splitlines()]
    chunks = []
    for offset in range(0, len(rows), hours_per_chunk):
        batch = rows[offset : offset + hours_per_chunk]
        identity = hashlib.sha256(
            json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        chunks.append(
            {
                "chunk_id": identity,
                "start_index": offset,
                "end_index_exclusive": offset + len(batch),
                "start_timestamp": batch[0]["timestamp_local"],
                "end_timestamp": batch[-1]["timestamp_local"],
                "hour_count": len(batch),
            }
        )
    payload = {
        "schema_version": "gridpulse-annual-execution-plan-v1",
        "chronology_sha256": hashlib.sha256(chronology_rows.read_bytes()).hexdigest(),
        "hour_count": len(rows),
        "hours_per_chunk": hours_per_chunk,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    target = destination / "annual-execution-plan.json"
    atomic_write(target, (json.dumps(payload, indent=2) + "\n").encode())
    return target


def execute_resumable(
    work_items: Iterable[dict[str, Any]],
    destination: Path,
    worker: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, int]:
    completed = failed = reused = 0
    for item in work_items:
        identity = hashlib.sha256(
            json.dumps(item, sort_keys=True, default=str).encode()
        ).hexdigest()
        target = destination / "work-units" / identity[:2] / f"{identity}.json"
        if target.exists():
            reused += 1
            continue
        try:
            result = {"status": "completed", "input": item, "result": worker(item)}
            completed += 1
        except (RuntimeError, ValueError) as error:
            result = {
                "status": "failed",
                "input": item,
                "error_type": type(error).__name__,
                "message": str(error),
            }
            failed += 1
        atomic_write(target, (json.dumps(result, indent=2, default=str) + "\n").encode())
    return {"completed": completed, "failed": failed, "reused": reused}
